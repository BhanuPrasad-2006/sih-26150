"""
verify.py — run the tool's own recovery, export and face analysis over a finished test pack and report what it finds.

The guide that ships with the pack is written from THESE observed numbers, not from hopes: if the tool changes and the
numbers change, regenerating the pack rewrites the guide.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2

DISKS = ["dahua_before_deletion.dd", "dahua_deleted.dd", "dahua_partly_overwritten.dd", "dahua_deleted_stress_tiny_clusters.dd", "cpplus_deleted.dd", "tplink_deleted.dd"]


def _embedding(path: Path):
    from backend import face_search
    ok, buf = cv2.imencode(".png", cv2.imread(str(path)))
    return face_search.extract_embedding_from_image_bytes(buf.tobytes())


def verify(pack: Path) -> dict:
    from backend import face_search
    from backend.acquisition import EvidenceImage
    from backend.exporter import export_segment
    from backend.face_detection import detect_faces_in_video
    from backend.pipeline import recover

    refs = {n: _embedding(pack / "people" / f"person_{n}.png") for n in ("A", "B")}
    out = {}
    for disk in DISKS:
        exports = Path(tempfile.mkdtemp(prefix="pack_verify_"))
        with EvidenceImage.open(pack / "disks" / disk) as img:
            sha = img.sha256_before
            res = recover(img)
            segs = []
            for seg in res.segments:
                seg2, detail = export_segment(img.mm, seg, exports)
                row = dict(camera=seg.camera, frames=seg.frame_count, status=seg2.status.value,
                           start=str(seg.start_time), end=str(seg.end_time), exported="error" not in detail,
                           decodes=bool(detail.get("ffprobe_valid")), faces_max_in_frame=None, best_similarity={})
                if row["exported"] and seg2.export_path:
                    f = detect_faces_in_video(seg2.export_path)
                    row["faces_max_in_frame"] = f.max_faces_in_single_frame
                    records = face_search.index_faces_for_search(seg2.export_path)
                    for name, emb in refs.items():
                        sims = [face_search.cosine_similarity(emb, r.embedding) for r in records]
                        row["best_similarity"][name] = round(max(sims), 2) if sims else None
                segs.append(row)
        out[disk] = dict(brand=res.brand, confidence=round(res.confidence, 2), generic=res.generic_fallback,
                         unidentified=res.unidentified, index_note=res.index_note, carve_note=res.carve_note, sha256=sha, segments=segs)
    out["_threshold"] = face_search.REFERENCE_MATCH_THRESHOLD
    out["_accuracy"] = _accuracy(pack)
    return out


def _accuracy(pack: Path) -> dict:
    """The validation kit run on generated ground truth: what the accuracy feature reports for known answers."""
    from backend.validation_kit import run_validation
    runs = {}
    for label, disk, clip, use_before in (
        ("deleted_vs_camera1_clip", "dahua_deleted.dd", "camera1_persons_A_and_B", True),
        ("deleted_vs_camera2_clip", "dahua_deleted.dd", "camera2_person_B_only", True),
        ("stress_vs_camera1_clip", "dahua_deleted_stress_tiny_clusters.dd", "camera1_persons_A_and_B", False),
    ):
        res = run_validation(pack / "disks" / disk, Path(tempfile.mkdtemp(prefix="pack_kit_")),
                             clip=pack / "truth_videos" / f"{clip}.mp4",
                             before=(pack / "disks" / "dahua_before_deletion.dd") if use_before else None, mode="exact")
        c, pl = res["combined"], res.get("placement") or {}
        runs[label] = dict(verdict=res["verdict"]["headline"], code=res["verdict"]["code"],
                           frame_recall=c["frame_recall_pct"], frame_precision=c["frame_precision_pct"],
                           in_order=c["in_order_pct"], byte_recall=pl.get("byte_recall_pct"))
    return runs
