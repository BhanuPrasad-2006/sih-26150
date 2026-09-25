"""
validation_kit.py — One command that turns real recorder disk images into a finished validation report.

    python -m backend.validation_kit --after deleted.dd --clip exported_clip.mp4 [--before original.dd]
                                     [--notes notes.json] [--log recordings.json] [--out validation_run]
                                     [--mode exact|perceptual] [--log-clock device|utc] [--offset MINUTES]

It runs the same recovery pipeline as the application (detect → index → carve → reconstruct → export), compares
what came back with the ground truth you supply, and writes:

    validation_report.md / .pdf   plain-language report with a verdict and a row for docs/VALIDATION_REPORT.md
    results.json                  every number, machine-readable
    exports/                      the recovered segments as MP4 (or raw streams if they would not remux)

Exit code 0 = run completed (read the verdict), 2 = bad input, 3 = an evidence image changed during the run.

What it can and cannot say: it measures ONE recovery on ONE device against the ground truth you gave it. It never
turns a single run into a general recovery rate, and anything you did not supply is reported as "not measured".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from backend import accuracy
from backend.acquisition import AcquisitionError, EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.pipeline import RecoveryResult, recover

KIT_VERSION = "1.0"
EXACT_MATCH_PCT = 99.0          # "recovered matches the ground truth" needs at least this on all three measures


class KitInputError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def _file_info(path: Path) -> dict:
    return {"name": path.name, "path": str(path.resolve()), "size_bytes": path.stat().st_size}


def _tool_versions() -> dict:
    v = {"kit": KIT_VERSION, "python": platform.python_version(), "platform": platform.platform()}
    try:
        line = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10).stdout.splitlines()[0]  # nosec B603 B607
        v["ffmpeg"] = line
    except Exception:
        v["ffmpeg"] = "not available"
    try:
        root = Path(__file__).resolve().parent.parent
        v["git_commit"] = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,  # nosec B603 B607
                                         text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        v["git_commit"] = "unknown"
    return v


def _pct(v) -> str:
    return "—" if v is None else f"{v:g}%"


def _segment_sort_key(seg):
    first = min((o.start for o in seg.disk_offsets), default=0)
    return (seg.start_time is None, seg.start_time or datetime.max.replace(tzinfo=timezone.utc), first)


def _hash_fn(mode: str) -> tuple[Callable, int]:
    return (accuracy.perceptual_frame_hashes, 6) if mode == "perceptual" else (accuracy.decoded_frame_hashes, 0)


# ── The run ───────────────────────────────────────────────────────────────────

def run_validation(
    after: Path,
    out_dir: Path,
    *,
    clip: Optional[Path] = None,
    before: Optional[Path] = None,
    notes: Optional[dict] = None,
    mode: str = "exact",
    log_entries: Optional[list[dict]] = None,
    log_clock: str = "device",
    utc_offset_minutes: Optional[int] = None,
    progress: Callable[[str], None] = print,
) -> dict:
    after = Path(after)
    for label, p in (("--after", after), ("--clip", clip), ("--before", before)):
        if p is not None and not Path(p).is_file():
            raise KitInputError(f"{label}: file not found: {p}")
    if mode not in ("exact", "perceptual"):
        raise KitInputError("--mode must be 'exact' or 'perceptual'")
    if before and Path(before).resolve() == after.resolve():
        raise KitInputError("--before and --after are the same file; the 'before' image must be taken before deleting.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exports = out_dir / "exports"
    t_start = time.monotonic()

    res: dict = {"kit_version": KIT_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
                 "tool": _tool_versions(), "notes": notes or {}, "mode": mode, "steps": []}

    def step(msg: str) -> None:
        res["steps"].append(msg)
        progress(msg)

    # 1. inputs and integrity baseline
    step("Fingerprinting the input files (SHA-256)…")
    inputs = {"after_image": _file_info(after)}
    inputs["after_image"]["sha256_before"] = _sha256(after)
    if before:
        inputs["before_image"] = _file_info(Path(before))
        inputs["before_image"]["sha256_before"] = _sha256(Path(before))
    if clip:
        inputs["ground_truth_clip"] = _file_info(Path(clip))
        inputs["ground_truth_clip"]["sha256"] = _sha256(Path(clip))
    res["inputs"] = inputs

    # 2. recover
    step("Scanning the after-deletion image (detect → index → carve → reconstruct)…")
    try:
        img = EvidenceImage.open(after)
    except AcquisitionError as exc:
        raise KitInputError(f"Cannot open the after-deletion image: {exc}")
    try:
        rec: RecoveryResult = recover(img, "validation-run")
        res["detection"] = {
            "brand": rec.brand, "brand_version": rec.brand_version, "confidence": round(rec.confidence, 3),
            "plugin": rec.plugin_name, "plugin_trust_wording": rec.plugin_display_name,
            "generic_fallback": rec.generic_fallback, "index_note": rec.index_note, "carve_note": rec.carve_note,
            "index_frames": rec.index_frames, "carved_frames": rec.carved_frames,
        }
        step(f"Brand: {rec.brand} (confidence {rec.confidence:.0%}); {len(rec.segments)} segment(s) reconstructed.")

        # 3. export
        segs = sorted(rec.segments, key=_segment_sort_key)
        seg_rows: list[dict] = []
        can_export = ffmpeg_available() and ffprobe_available()
        if segs and not can_export:
            step("ffmpeg/ffprobe not found: segments cannot be exported or compared.")
        for i, seg in enumerate(segs, 1):
            row = {"n": i, "segment_id": seg.segment_id, "camera": seg.camera,
                   "start_time": seg.start_time.isoformat() if seg.start_time else None,
                   "end_time": seg.end_time.isoformat() if seg.end_time else None,
                   "frame_count": seg.frame_count, "status": seg.status.value if hasattr(seg.status, "value") else str(seg.status),
                   "notes": seg.notes, "disk_bytes": sum(o.end - o.start for o in seg.disk_offsets),
                   "exported": False, "export_file": None, "ffprobe_valid": None}
            if can_export:
                step(f"Exporting segment {i}/{len(segs)}…")
                seg2, detail = export_segment(img.mm, seg, exports)
                seg = seg2
                row["status"] = seg.status.value if hasattr(seg.status, "value") else str(seg.status)
                if seg.export_path and Path(seg.export_path).is_file():
                    row.update(exported=True, export_file=Path(seg.export_path).name,
                               export_sha256=seg.sha256, ffprobe_valid=detail.get("ffprobe_valid", None))
                    if row["ffprobe_valid"] is None:
                        row["ffprobe_valid"] = row["status"] in ("PARTIAL", "COMPLETE")
                if detail.get("error"):
                    row["export_error"] = detail["error"]
            seg_rows.append(row)
            segs[i - 1] = seg
        res["segments"] = seg_rows

        # 4. ground truth: video
        res["ground_truth"] = {"supplied": bool(clip)}
        not_measured: list[str] = []
        if clip:
            hash_fn, thr = _hash_fn(mode)
            step("Decoding the ground-truth clip…")
            try:
                truth = hash_fn(Path(clip))
            except Exception as exc:
                truth = None
                not_measured.append(f"frames: could not decode the ground-truth clip ({exc})")
            if truth is not None:
                res["ground_truth"]["clip_frames"] = len(truth)
                per_seg: list[list] = []
                for row, seg in zip(seg_rows, segs):
                    if not row["exported"]:
                        per_seg.append([])
                        continue
                    step(f"Comparing segment {row['n']} with the clip…")
                    try:
                        hashes = hash_fn(Path(seg.export_path))
                    except Exception as exc:
                        row["compare_error"] = str(exc)
                        per_seg.append([])
                        continue
                    per_seg.append(hashes)
                    row["frames"] = accuracy.match_frame_sequences(truth, hashes, max_distance=thr)
                    row["bytes"] = accuracy.compare_bytes(Path(seg.export_path), Path(clip))
                combined_hashes = [h for lst in per_seg for h in lst]
                res["combined"] = accuracy.match_frame_sequences(truth, combined_hashes, max_distance=thr) if combined_hashes else None
                res["combined_note"] = ("All exported segments concatenated in time order and matched against the clip: "
                                        "this is the fair 'how much of the clip came back' number when the recording was "
                                        "split into several segments.")
        else:
            not_measured.append("frames and bytes: no ground-truth clip was supplied")

        # 5. placement against the original disk
        if before:
            step("Measuring where the recovered bytes came from (against the before-deletion image)…")
            try:
                ref, source = accuracy.reference_ranges_from_original(str(before))
                rec_ranges = {s.segment_id: [(o.start, o.end) for o in s.disk_offsets] for s in segs}
                res["placement"] = accuracy.placement_report(ref, rec_ranges, source)
            except Exception as exc:
                not_measured.append(f"placement: {exc}")
        else:
            not_measured.append("placement: no before-deletion image was supplied")

        # 6. recording log
        if log_entries:
            try:
                res["log"] = accuracy.compare_to_log(segs, log_entries, utc_offset_minutes, log_clock)
            except Exception as exc:
                not_measured.append(f"time/camera: {exc}")
        else:
            not_measured.append("time/camera: no recording log was supplied")
        res["not_measured"] = not_measured

        # 7. integrity: did the run change the evidence?
        step("Re-checking that the evidence was not changed by this run…")
        unchanged = img.verify_unchanged()
    finally:
        img.close()

    after_sha = _sha256(after)
    inputs["after_image"]["sha256_after"] = after_sha
    inputs["after_image"]["unchanged"] = bool(unchanged and after_sha == inputs["after_image"]["sha256_before"])
    if before:
        b_after = _sha256(Path(before))
        inputs["before_image"]["sha256_after"] = b_after
        inputs["before_image"]["unchanged"] = b_after == inputs["before_image"]["sha256_before"]
    res["evidence_unchanged"] = all(v.get("unchanged", True) for v in inputs.values() if isinstance(v, dict))
    res["verdict"] = decide(res)
    res["duration_seconds"] = round(time.monotonic() - t_start, 1)
    return res


# ── Verdict ───────────────────────────────────────────────────────────────────

def decide(res: dict) -> dict:
    """A cautious one-line conclusion. It only says what the supplied evidence supports."""
    det = res.get("detection", {})
    segs = res.get("segments", [])
    exported = [s for s in segs if s.get("exported")]
    decoded = [s for s in exported if s.get("ffprobe_valid")]
    facts: list[str] = []
    if not res.get("evidence_unchanged", True):
        return {"code": "EVIDENCE_CHANGED", "headline": "STOP: an evidence image changed during the run.",
                "details": ["The SHA-256 of an input image differs after the run. Do not use these results; investigate."]}
    facts.append(f"Brand detected: {det.get('brand')} (confidence {det.get('confidence')}); "
                 f"generic fallback: {'yes' if det.get('generic_fallback') else 'no'}.")
    if not segs:
        return {"code": "NO_VIDEO", "headline": "Nothing recoverable was found.",
                "details": facts + ["No segments were reconstructed. Either the footage is gone, or this recorder's layout is "
                                    "not handled correctly by the tool. Send the report so the parser can be examined."]}
    if not decoded:
        return {"code": "NO_DECODABLE_VIDEO", "headline": f"{len(segs)} segment(s) found but none decodes as video.",
                "details": facts + ["Data was located but ffprobe could not decode any export. The carving boundaries or the "
                                    "container assumptions may be wrong for this device."]}
    comb = res.get("combined")
    if not res.get("ground_truth", {}).get("supplied") or comb is None:
        return {"code": "NOT_MEASURED", "headline": f"{len(decoded)} decodable segment(s) recovered; accuracy NOT MEASURED (no usable ground truth).",
                "details": facts + ["Supply the clip exported before deletion to get recall, precision and order."]}
    r, p, o = comb["frame_recall_pct"], comb["frame_precision_pct"], comb["in_order_pct"]
    details = facts + [f"Frames recovered {_pct(r)}, frames that are right {_pct(p)}, in correct order {_pct(o)} "
                       f"(mode: {res['mode']}, {res['ground_truth'].get('clip_frames')} frames in the clip)."]
    if all(v is not None and v >= EXACT_MATCH_PCT for v in (r, p, o)):
        return {"code": "MATCHES", "headline": "The recovered video matches the ground-truth clip.", "details": details}
    if r is not None and r >= EXACT_MATCH_PCT:
        return {"code": "COMPLETE_WITH_EXTRAS",
                "headline": f"Every frame of the clip came back, along with other footage (precision {_pct(p)}, order {_pct(o)}).",
                "details": details + ["Extra frames are expected when the disk holds other recordings; low order means fragments were "
                                      "reassembled in the wrong sequence."]}
    if r is not None and r > 0:
        return {"code": "PARTIAL_MATCH", "headline": f"Partly recovered: {_pct(r)} of the clip's frames came back.", "details": details}
    return {"code": "NO_MATCH", "headline": "Video was recovered, but none of it matches the ground-truth clip.",
            "details": details + ["Either the clip is not the same recording, or the recovered data is from another period."]}


# ── Reports ───────────────────────────────────────────────────────────────────

def _blocks(res: dict) -> list[tuple]:
    inp, det, v = res["inputs"], res.get("detection", {}), res["verdict"]
    notes = res.get("notes", {})
    b: list[tuple] = [("title", "Recorder Validation Report"),
                      ("p", f"Generated {res['created_utc']} by the SIH DVR/NVR Forensic Tool validation kit v{res['kit_version']}. "
                            f"Run time {res.get('duration_seconds', '?')} s.")]
    b += [("h2", "Verdict"), ("verdict", v["headline"]), ("bullets", v["details"]),
          ("p", "This is one recovery on one device measured against the ground truth supplied. It is not a general recovery rate.")]

    rows = [["Item", "Value"]]
    for k in ("data_source", "vendor", "model", "firmware", "disk", "scenario", "time_zone", "operator", "remarks"):
        if notes.get(k):
            rows.append([k.replace("_", " ").capitalize(), str(notes[k])])
    b += [("h2", "Test details"), ("table", rows if len(rows) > 1 else [["Item", "Value"], ["Notes", "no notes file supplied"]])]

    irows = [["File", "Size (bytes)", "SHA-256 before run", "Unchanged by run"]]
    for label, key in (("After-deletion image", "after_image"), ("Before-deletion image", "before_image")):
        if key in inp:
            i = inp[key]
            irows.append([f"{label}: {i['name']}", f"{i['size_bytes']:,}", i["sha256_before"], "yes" if i.get("unchanged") else "NO"])
    if "ground_truth_clip" in inp:
        c = inp["ground_truth_clip"]
        irows.append([f"Ground-truth clip: {c['name']}", f"{c['size_bytes']:,}", c["sha256"], "n/a"])
    b += [("h2", "Evidence integrity"), ("table", irows)]

    b += [("h2", "What the tool detected"),
          ("table", [["Brand", str(det.get("brand"))], ["Confidence", str(det.get("confidence"))],
                     ["Plugin (trust wording)", str(det.get("plugin_trust_wording"))],
                     ["Generic fallback used", "yes" if det.get("generic_fallback") else "no"],
                     ["Index", str(det.get("index_note"))], ["Carving", str(det.get("carve_note"))],
                     ["Frames from index / carved", f"{det.get('index_frames')} / {det.get('carved_frames')}"]])]

    srows = [["#", "Camera", "Frames", "Status", "Decodes", "Frames recovered", "Frames right", "In order", "Byte-identical"]]
    for s in res.get("segments", []):
        f, by = s.get("frames"), s.get("bytes")
        srows.append([str(s["n"]), str(s["camera"]), str(s["frame_count"]), s["status"],
                      {True: "yes", False: "no", None: "n/a"}[s.get("ffprobe_valid")],
                      _pct(f["frame_recall_pct"]) if f else "—", _pct(f["frame_precision_pct"]) if f else "—",
                      _pct(f["in_order_pct"]) if f else "—", ("yes" if by["identical"] else "no") if by else "—"])
    b += [("h2", "Recovered segments"), ("table", srows if len(srows) > 1 else [["Result"], ["no segments"]]),
          ("p", "Byte-identical is normally 'no' even for a perfect recovery, because the export is re-wrapped into MP4; "
                "the frame columns are what show whether the video came back. A segment that belongs to another recording "
                "shows 0% here, which is expected.")]

    comb = res.get("combined")
    if comb:
        b += [("h2", "All segments together vs the clip"),
              ("table", [["Measure", "Result"], ["Frames recovered (recall)", _pct(comb["frame_recall_pct"])],
                         ["Frames that are right (precision)", _pct(comb["frame_precision_pct"])],
                         ["In correct order", _pct(comb["in_order_pct"])],
                         ["Frames in the clip", str(res["ground_truth"].get("clip_frames"))]]),
              ("p", res.get("combined_note", ""))]
    pl = res.get("placement")
    if pl:
        b += [("h2", "Where the recovered bytes came from"),
              ("table", [["Measure", "Result"], ["Original bytes recovered", _pct(pl.get("byte_recall_pct"))],
                         ["Recovered bytes from the right place", _pct(pl.get("placement_precision_pct"))],
                         ["Reference used", str(pl.get("reference_source"))]])]
    lg = res.get("log")
    if lg:
        lrows = [["Log entry", "Time coverage", "Start offset (s)", "End offset (s)"]]
        for e in lg["entries"]:
            lrows.append([str(e.get("name")), _pct(e.get("time_coverage_pct")), str(e.get("start_delta_seconds")), str(e.get("end_delta_seconds"))])
        b += [("h2", "Times and cameras vs the recording log"), ("table", lrows)]
    b += [("h2", "Not measured"), ("bullets", res.get("not_measured") or ["nothing: every supplied check was run"])]

    row = [notes.get("vendor", "?") + " / " + notes.get("model", "?"), notes.get("disk", "?"), notes.get("scenario", "deleted via menu"),
           str(det.get("brand")), _pct(comb["frame_recall_pct"]) if comb else "not measured",
           _pct(comb["frame_precision_pct"]) if comb else "—", _pct(comb["in_order_pct"]) if comb else "—",
           (_pct(pl.get("byte_recall_pct")) + " / " + _pct(pl.get("placement_precision_pct"))) if pl else "not measured", "—", v["code"]]
    b += [("h2", "Row for docs/VALIDATION_REPORT.md, section 7"),
          ("table", [["Vendor / model", "Disk & size", "Scenario", "Brand detected", "Frame recall", "Precision", "In order",
                      "Byte recall / placement", "Time offset error", "Verdict"], row]),
          ("h2", "Reproduce"), ("p", "python -m backend.validation_kit --after <after.dd> --clip <clip> [--before <before.dd>] "
                                     f"--mode {res['mode']}  (tool commit {res['tool'].get('git_commit')}, {res['tool'].get('ffmpeg')})")]
    return b


def write_markdown(res: dict, path: Path) -> None:
    out: list[str] = []
    for kind, content in _blocks(res):
        if kind == "title":
            out.append(f"# {content}\n")
        elif kind == "h2":
            out.append(f"\n## {content}\n")
        elif kind == "verdict":
            out.append(f"> **{content}**\n")
        elif kind == "p":
            out.append(f"{content}\n")
        elif kind == "bullets":
            out.extend(f"- {x}" for x in content)
            out.append("")
        elif kind == "table":
            out.append("| " + " | ".join(content[0]) + " |")
            out.append("|" + "|".join("---" for _ in content[0]) + "|")
            for r in content[1:]:
                out.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
            out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def write_pdf(res: dict, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=7.5, leading=9)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="Recorder Validation Report")
    el: list = []
    for kind, content in _blocks(res):
        if kind == "title":
            el.append(Paragraph(content, ss["Title"]))
        elif kind == "h2":
            el += [Spacer(1, 0.3 * cm), Paragraph(content, ss["Heading2"])]
        elif kind == "verdict":
            el.append(Paragraph(f"<b>{content}</b>", ss["Heading3"]))
        elif kind == "p":
            el.append(Paragraph(content, ss["BodyText"]))
        elif kind == "bullets":
            for x in content:
                el.append(Paragraph("• " + x, ss["BodyText"]))
        elif kind == "table":
            data = [[Paragraph(str(c), small) for c in r] for r in content]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F5")),
                                   ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            el.append(t)
    doc.build(el)


def write_outputs(res: dict, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "results.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    write_markdown(res, out_dir / "validation_report.md")
    write_pdf(res, out_dir / "validation_report.pdf")
    return {"json": out_dir / "results.json", "markdown": out_dir / "validation_report.md", "pdf": out_dir / "validation_report.pdf"}


# ── Command line ──────────────────────────────────────────────────────────────

def _load_json(path: Optional[str], what: str):
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise KitInputError(f"{what}: {exc}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.validation_kit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", required=True, help="disk image taken AFTER the recording was deleted (.dd)")
    ap.add_argument("--clip", help="the same clip exported from the recorder BEFORE deleting (ground truth)")
    ap.add_argument("--before", help="disk image taken BEFORE deleting (optional, enables byte-placement measurement)")
    ap.add_argument("--notes", help="JSON file: vendor, model, firmware, disk, scenario, time_zone, operator, remarks")
    ap.add_argument("--log", help="recording log JSON, see docs/accuracy_measurement.md")
    ap.add_argument("--log-clock", choices=["device", "utc"], default="device")
    ap.add_argument("--offset", type=int, help="recorder clock offset from UTC in minutes (needed with --log-clock utc)")
    ap.add_argument("--mode", choices=["exact", "perceptual"], default="exact",
                    help="exact: clip is the same stream re-wrapped; perceptual: the vendor player re-encoded it (upper bound)")
    ap.add_argument("--out", default="validation_run", help="output folder (default: validation_run)")
    a = ap.parse_args(argv)

    try:
        notes = _load_json(a.notes, "--notes") or {}
        log = _load_json(a.log, "--log")
        if isinstance(log, dict):
            log = log.get("recordings")
        res = run_validation(Path(a.after), Path(a.out), clip=Path(a.clip) if a.clip else None,
                             before=Path(a.before) if a.before else None, notes=notes, mode=a.mode,
                             log_entries=log, log_clock=a.log_clock, utc_offset_minutes=a.offset)
    except KitInputError as exc:
        print(f"Input problem: {exc}", file=sys.stderr)
        return 2
    paths = write_outputs(res, Path(a.out))
    v = res["verdict"]
    print("\n" + "=" * 70)
    print("VERDICT:", v["headline"])
    for d in v["details"]:
        print("  -", d)
    print("Report:", paths["pdf"], "\n       ", paths["markdown"], "\n       ", paths["json"])
    return 3 if v["code"] == "EVIDENCE_CHANGED" else 0


if __name__ == "__main__":
    sys.exit(main())
