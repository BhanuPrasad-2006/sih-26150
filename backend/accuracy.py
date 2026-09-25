"""
accuracy.py — measure recovery against GROUND TRUTH the examiner supplies.

The tool cannot know how much footage there should have been, so it never reports a
recovery percentage on its own. These measurements exist only when ground truth is given:

  1. compare_bytes        recovered export vs a ground-truth file: byte-exact? first mismatch?
  2. compare_frames       decode both; what fraction of the truth frames came back, how many
                          extra/wrong frames, and are they in the right order?
  3. compare_to_log       recovered camera/time windows vs the examiner's recording log
  4. placement_report     recovered disk byte ranges vs the ORIGINAL disk's own index (or, for
                          formats with no index parser, the same tool run on the original image)

Each function returns plain dicts (JSON-serialisable) and states in the result what the number
does and does not prove. A missing input yields "not measured", never a guess.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from backend.sandbox import FFMPEG_SAFE_INPUT, run_limited

log = logging.getLogger(__name__)

_CHUNK = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _pct(num: float, den: float) -> Optional[float]:
    return round(100.0 * num / den, 2) if den else None


# ── 1. Bytes ──────────────────────────────────────────────────────────────────

def compare_bytes(recovered: Path, truth: Path) -> dict:
    """
    Byte-exact comparison. `identical` means the two files are the same bytes. `positional_match_pct`
    is the share of byte positions that agree (over the longer file), which drops sharply if data is
    shifted; it is NOT a measure of recovered content.
    """
    import numpy as np

    rs, ts = recovered.stat().st_size, truth.stat().st_size
    first_mismatch: Optional[int] = None
    matching = 0
    pos = 0
    with open(recovered, "rb") as fa, open(truth, "rb") as fb:
        while True:
            a, b = fa.read(_CHUNK), fb.read(_CHUNK)
            if not a and not b:
                break
            n = min(len(a), len(b))
            if n:
                eq = np.frombuffer(a[:n], dtype=np.uint8) == np.frombuffer(b[:n], dtype=np.uint8)
                matching += int(eq.sum())
                if first_mismatch is None and not eq.all():
                    first_mismatch = pos + int(np.argmin(eq))
            if len(a) != len(b) and first_mismatch is None:
                first_mismatch = pos + n
            pos += max(len(a), len(b))
    rh, th = _sha256(recovered), _sha256(truth)
    return {
        "recovered_size": rs, "truth_size": ts,
        "recovered_sha256": rh, "truth_sha256": th,
        "identical": rh == th,
        "first_mismatch_offset": None if rh == th else first_mismatch,
        "positional_match_pct": _pct(matching, max(rs, ts)),
        "meaning": (
            "Identical: the recovered file is byte-for-byte the ground-truth file."
            if rh == th else
            "Different bytes. Compare frames (below): a re-muxed or re-exported copy of the same video "
            "differs at byte level but can still contain every frame."
        ),
    }


# ── 2. Frames ─────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    # Ground-truth videos come from outside the tool: limited, secret-free, local-files-only.
    return run_limited(cmd, timeout=timeout)


def decoded_frame_hashes(path: Path, timeout: int = 900) -> list[str]:
    """MD5 of every decoded video frame (yuv420p) via ffmpeg's framemd5 muxer."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not on PATH")
    res = _run(["ffmpeg", "-v", "error", "-nostdin", *FFMPEG_SAFE_INPUT, "-i", str(path), "-map", "0:v:0", "-an", "-sn",
                "-pix_fmt", "yuv420p", "-f", "framemd5", "-"], timeout)
    if res.returncode != 0 and not res.stdout.strip():
        raise RuntimeError(f"could not decode {path.name}: {res.stderr.strip()[:200]}")
    hashes = []
    for line in res.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        hashes.append(line.rsplit(",", 1)[-1].strip())
    return hashes


def perceptual_frame_hashes(path: Path, max_frames: int = 200_000) -> list[int]:
    """64-bit average hash of every decoded frame (tolerates re-encoding)."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {path.name}")
    out: list[int] = []
    try:
        while len(out) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (8, 8), interpolation=cv2.INTER_AREA)
            bits = (g > g.mean()).flatten()
            v = 0
            for b in bits:
                v = (v << 1) | int(b)
            out.append(v)
    finally:
        cap.release()
    return out


def _lis_length(seq: list[int]) -> int:
    tails: list[int] = []
    for x in seq:
        i = bisect.bisect_left(tails, x)
        if i == len(tails):
            tails.append(x)
        else:
            tails[i] = x
    return len(tails)


def _ranges(indices: Iterable[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for i in sorted(indices):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def match_frame_sequences(truth: list, recovered: list, max_distance: int = 0) -> dict:
    """
    Match recovered frames to truth frames. Items are hashes (exact: max_distance=0) or 64-bit
    ints compared by Hamming distance <= max_distance (perceptual). Each truth frame can be
    matched at most once, so duplicated content (a static scene) is counted honestly.
    Returns recall/precision and how many matched frames are in the right order.
    """
    truth_n, rec_n = len(truth), len(recovered)
    used = [False] * truth_n
    matched_truth_idx: list[int] = []      # truth index for each matched recovered frame, in recovered order

    if max_distance == 0:
        from collections import defaultdict, deque
        where: dict = defaultdict(deque)
        for i, h in enumerate(truth):
            where[h].append(i)
        last = -1
        for h in recovered:
            q = where.get(h)
            if not q:
                continue
            # prefer the earliest unused truth index after the last match (keeps order), else earliest anywhere
            pick = next((i for i in q if i > last), q[0])
            q.remove(pick)
            matched_truth_idx.append(pick)
            last = pick
    else:
        import numpy as np
        t = np.array(truth, dtype=np.uint64)
        popcount = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
        last = -1
        for h in recovered:
            if truth_n == 0:
                break
            x = (t ^ np.uint64(h)).view(np.uint8).reshape(-1, 8)
            dist = popcount[x].sum(axis=1)
            dist[np.array(used)] = 255
            cand = np.where(dist <= max_distance)[0]
            if cand.size == 0:
                continue
            after = cand[cand > last]
            pick = int(after[np.argmin(dist[after])]) if after.size else int(cand[np.argmin(dist[cand])])
            used[pick] = True
            matched_truth_idx.append(pick)
            last = pick

    matched = len(matched_truth_idx)
    in_order = _lis_length(matched_truth_idx)
    missing = set(range(truth_n)) - set(matched_truth_idx)
    return {
        "truth_frames": truth_n, "recovered_frames": rec_n, "matched_frames": matched,
        "missing_frames": truth_n - matched, "extra_or_wrong_frames": rec_n - matched,
        "frame_recall_pct": _pct(matched, truth_n),
        "frame_precision_pct": _pct(matched, rec_n),
        "in_order_pct": _pct(in_order, matched),
        "missing_ranges": _ranges(missing)[:50],
        "missing_ranges_truncated": len(_ranges(missing)) > 50,
    }


def compare_frames(recovered: Path, truth: Path, mode: str = "exact", perceptual_threshold: int = 6) -> dict:
    """
    exact       — identical decoded pixels. Right when the truth was exported by remuxing the same
                  stream (no re-encode).
    perceptual  — tolerant 8x8 hash (Hamming <= threshold). Use when the vendor player re-encoded;
                  it can also accept visually similar but different frames, so treat as an upper bound.
    """
    if mode == "perceptual":
        t, r = perceptual_frame_hashes(truth), perceptual_frame_hashes(recovered)
        res = match_frame_sequences(t, r, max_distance=perceptual_threshold)
        note = ("Perceptual match (8x8 average hash, Hamming <= %d). Similar-looking frames can match; this is an "
                "upper bound on recovery, not proof of identical content." % perceptual_threshold)
    else:
        t, r = decoded_frame_hashes(truth), decoded_frame_hashes(recovered)
        res = match_frame_sequences(t, r)
        note = "Exact match of decoded frame pixels (MD5 per frame)."
    res["mode"] = mode
    res["meaning"] = note + (
        " Recall = share of ground-truth frames that were recovered; precision = share of recovered frames that "
        "are in the ground truth; in-order = share of matched frames that appear in the same order."
    )
    return res


# ── 3. Time and camera vs the examiner's log ─────────────────────────────────

def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compare_to_log(segments: list, log_entries: list[dict], device_utc_offset_minutes: Optional[int] = None,
                   log_clock: str = "device") -> dict:
    """
    Each log entry: {"name": str, "camera": int (optional), "start": ISO time, "end": ISO time}.
    log_clock "device": the log uses the recorder's own clock (same convention as the segment times).
    log_clock "utc":    the log is in UTC; segment times are converted with the evidence's clock offset
                        (required; no guessing).
    """
    if log_clock not in ("device", "utc"):
        raise ValueError("log_clock must be 'device' or 'utc'")
    if log_clock == "utc" and device_utc_offset_minutes is None:
        raise ValueError("log_clock 'utc' needs the evidence's device clock offset (none was set)")

    def seg_window(s) -> Optional[tuple[datetime, datetime]]:
        if s.start_time is None or s.end_time is None:
            return None
        a, b = s.start_time, s.end_time
        if a.tzinfo is None:
            a, b = a.replace(tzinfo=timezone.utc), b.replace(tzinfo=timezone.utc)
        if log_clock == "utc":
            d = timedelta(minutes=device_utc_offset_minutes)
            a, b = a - d, b - d
        return a, b

    rows = []
    for e in log_entries:
        t0, t1 = _parse_dt(e["start"]), _parse_dt(e["end"])
        dur = max((t1 - t0).total_seconds(), 0.0)
        cam = e.get("camera")
        cover: list[tuple[datetime, datetime]] = []
        best = None
        for s in segments:
            if cam is not None and s.camera != cam:
                continue
            w = seg_window(s)
            if w is None:
                continue
            lo, hi = max(w[0], t0), min(w[1], t1)
            if hi > lo:
                cover.append((lo, hi))
                if best is None or (hi - lo) > (best[1] - best[0]):
                    best = (lo, hi, s, w)
        cover.sort()
        covered = 0.0
        cur_end = None
        for lo, hi in cover:
            if cur_end is None or lo > cur_end:
                covered += (hi - lo).total_seconds()
                cur_end = hi
            elif hi > cur_end:
                covered += (hi - cur_end).total_seconds()
                cur_end = hi
        row = {
            "name": e.get("name", ""), "camera": cam,
            "truth_start": t0.isoformat(), "truth_end": t1.isoformat(), "truth_seconds": dur,
            "covered_seconds": round(covered, 2), "time_coverage_pct": _pct(covered, dur),
            "matching_segments": len(cover),
        }
        if best is not None:
            _, _, s, w = best
            row.update({"best_segment_id": s.segment_id,
                        "start_delta_seconds": round((w[0] - t0).total_seconds(), 2),
                        "end_delta_seconds": round((w[1] - t1).total_seconds(), 2)})
        rows.append(row)
    return {
        "entries": rows,
        "meaning": ("Time coverage = share of each logged recording's time span that recovered segments of the same "
                    "camera overlap. Positive start delta = the recovered footage begins later than the log says."),
    }


# ── 4. Placement on disk ─────────────────────────────────────────────────────

def _merge(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(r for r in ranges if r[1] > r[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> int:
    """Bytes covered by both merged, sorted range lists."""
    i = j = total = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            total += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def placement_report(reference: dict[str, list[tuple[int, int]]], recovered: dict[str, list[tuple[int, int]]],
                     reference_source: str) -> dict:
    """
    reference: {original recording id: [(start, end), ...]} — byte ranges on the ORIGINAL disk.
    recovered: {recovered segment id: [(start, end), ...]} — byte ranges the tool read from the
               (deleted) disk image. Both are absolute offsets in the same disk geometry.
    """
    ref = {k: _merge(v) for k, v in reference.items()}
    rec = {k: _merge(v) for k, v in recovered.items()}
    all_ref = _merge(r for v in ref.values() for r in v)
    all_rec = _merge(r for v in rec.values() for r in v)
    total_ref = sum(b - a for a, b in all_ref)
    total_rec = sum(b - a for a, b in all_rec)
    both = _overlap(all_ref, all_rec)

    per_original = []
    for k, rr in ref.items():
        size = sum(b - a for a, b in rr)
        got = _overlap(rr, all_rec)
        per_original.append({"original": k, "bytes": size, "recovered_bytes": got, "byte_recall_pct": _pct(got, size)})

    per_segment = []
    for k, sr in rec.items():
        size = sum(b - a for a, b in sr)
        shares = {o: _overlap(sr, rr) for o, rr in ref.items()}
        in_any = _overlap(sr, all_ref)
        dominant = max(shares, key=shares.get) if shares and max(shares.values()) > 0 else None
        touching = [o for o, v in shares.items() if v > 0]
        per_segment.append({
            "segment": k, "bytes": size, "bytes_at_original_locations": in_any,
            "placed_pct": _pct(in_any, size), "dominant_original": dominant,
            "dominant_share_pct": _pct(shares[dominant], size) if dominant else None,
            "mixes_several_originals": len(touching) > 1,
        })
    return {
        "reference_source": reference_source,
        "original_bytes": total_ref, "recovered_bytes": total_rec, "recovered_bytes_at_original_locations": both,
        "byte_recall_pct": _pct(both, total_ref),
        "placement_precision_pct": _pct(both, total_rec),
        "per_original": per_original, "per_segment": per_segment,
        "meaning": (
            "Byte recall = share of the original recordings' bytes that recovered segments cover. Placement precision = "
            "share of recovered bytes that lie inside an original recording's location. Both are computed from disk "
            "offsets, so they check WHERE bytes came from, not what the video shows. Source of the reference: "
            + reference_source
        ),
    }


def reference_ranges_from_original(image_path: str) -> tuple[dict[str, list[tuple[int, int]]], str]:
    """
    Where the recordings were on the ORIGINAL (pre-deletion) disk.
    Dahua DHFS 4.1: the disk's own index (independent of our carving).
    Anything else: our carver run on the original image — this measures what deletion cost, not whether the
    carver is right, and the result says so.
    """
    from backend.acquisition import EvidenceImage
    from backend.plugins.dahua_dhfs import iter_recordings, read_partitions
    from backend.reconstructor import label_all

    with EvidenceImage.open(image_path) as img:
        parts = read_partitions(img.mm, img.size)
        if parts:
            ref: dict[str, list[tuple[int, int]]] = {}
            for p in parts:
                for rec in iter_recordings(img.mm, img.size, p):
                    ref[f"p{p.number} recording {rec.main_index} (camera {rec.camera})"] = [
                        (f.offset, f.offset + f.size) for f in rec.fragments]
            return ref, "the ORIGINAL disk's own DHFS 4.1 index (descriptor chains)"

        from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE
        from backend.plugins.generic import GenericStreamPlugin
        from backend.plugins.registry import detect_brand
        brand, _v, conf, plugin = detect_brand(img)
        if conf < MIN_PLUGIN_CONFIDENCE:          # same fallback the scan pipeline uses
            plugin, brand = GenericStreamPlugin(), "generic stream carving"
        frames, _note = plugin.carve(img)
        segs = label_all(frames, "reference")
        ref = {f"segment {i} (camera {s.camera})": [(o.start, o.end) for o in s.disk_offsets] for i, s in enumerate(segs)}
        return ref, (f"the same carver ({brand}) run on the ORIGINAL image — this measures what deletion cost, "
                     "not whether the carver itself is right")


# ── Orchestration ────────────────────────────────────────────────────────────

@dataclass
class AccuracyInputs:
    segment: object                                   # models.Segment (must be exported for frame/byte checks)
    all_segments: list                                # every segment of the evidence
    truth_file: Optional[Path] = None
    log_entries: Optional[list[dict]] = None
    log_clock: str = "device"
    original_image: Optional[str] = None
    mode: str = "exact"
    device_utc_offset_minutes: Optional[int] = None


def run_accuracy_check(inp: AccuracyInputs) -> dict:
    """Run every check the supplied ground truth allows; the rest are reported as not measured."""
    out: dict = {"created_at": datetime.now(timezone.utc).isoformat(), "segment_id": inp.segment.segment_id,
                 "camera": inp.segment.camera, "mode": inp.mode}
    measured, not_measured = [], []
    exp = Path(inp.segment.export_path) if inp.segment.export_path else None

    if inp.truth_file is not None:
        if exp is None or not exp.is_file():
            not_measured.append("bytes and frames: this segment has not been exported yet")
        else:
            out["bytes"] = compare_bytes(exp, inp.truth_file)
            measured.append("bytes")
            try:
                out["frames"] = compare_frames(exp, inp.truth_file, inp.mode)
                measured.append("frames")
            except Exception as exc:
                out["frames_error"] = str(exc)
                not_measured.append(f"frames: {exc}")
    else:
        not_measured.append("bytes and frames: no ground-truth video was supplied")

    if inp.log_entries:
        try:
            out["log"] = compare_to_log(inp.all_segments, inp.log_entries, inp.device_utc_offset_minutes, inp.log_clock)
            measured.append("time/camera")
        except Exception as exc:
            not_measured.append(f"time/camera: {exc}")
    else:
        not_measured.append("time/camera: no recording log was supplied")

    if inp.original_image:
        try:
            ref, source = reference_ranges_from_original(inp.original_image)
            rec = {s.segment_id: [(o.start, o.end) for o in s.disk_offsets] for s in inp.all_segments}
            out["placement"] = placement_report(ref, rec, source)
            measured.append("placement")
        except Exception as exc:
            log.warning("placement check failed: %s", exc)
            not_measured.append(f"placement: {exc}")
    else:
        not_measured.append("placement: no original (pre-deletion) disk image was supplied")

    out["measured"], out["not_measured"] = measured, not_measured
    return out


def summarize(result: dict) -> str:
    """One-line human summary for the audit log."""
    parts = []
    f = result.get("frames")
    if f:
        parts.append(f"frame recall {f['frame_recall_pct']}% / precision {f['frame_precision_pct']}% / in-order {f['in_order_pct']}%")
    b = result.get("bytes")
    if b:
        parts.append("byte-identical" if b["identical"] else "not byte-identical")
    p = result.get("placement")
    if p:
        parts.append(f"byte recall {p['byte_recall_pct']}% / placement precision {p['placement_precision_pct']}%")
    lg = result.get("log")
    if lg:
        vals = [e["time_coverage_pct"] for e in lg["entries"] if e["time_coverage_pct"] is not None]
        if vals:
            parts.append("time coverage " + ", ".join(f"{v}%" for v in vals))
    return "; ".join(parts) or "nothing measured"
