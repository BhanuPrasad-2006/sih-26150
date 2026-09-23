"""
e2e_honeywell_real_video_verification.py — Manual end-to-end verification for the
Honeywell plugin (NOT collected by pytest; needs ffmpeg and two local face photos).

Builds a REAL H.264 video of a face, splits it into per-picture payloads, wraps each
in a Honeywell 20-byte record header (layout: Yoon & Hwang, arXiv:2605.07430), places
two overlapping "channel" streams plus decoys in a GPT-style image, and runs the real
pipeline: detect -> carve -> reconstruct -> export -> ffprobe -> face detection ->
face search (same person vs different person).

What this does NOT prove: that a real Honeywell disk matches this layout on models other
than the paper's (HN35080200). The record header's field values were checked against the
bytes/values printed in the paper (see backend/tests/test_honeywell.py).

Usage: see e2e_real_video_verification.py (same two photos in ./_scratch/).
"""
import mmap
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from e2e_real_video_verification import PERSON_A, PERSON_B, SCRATCH, build_h264_stream  # noqa: E402

from backend.acquisition import EvidenceImage  # noqa: E402
from backend.exporter import export_segment, ffprobe_check  # noqa: E402
from backend.face_detection import detect_faces_in_video  # noqa: E402
from backend.face_search import (  # noqa: E402
    cosine_similarity,
    extract_embedding_from_image_bytes,
    index_faces_for_search,
)
from backend.models import SegmentStatus  # noqa: E402
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE  # noqa: E402
from backend.plugins.honeywell import HoneywellPlugin  # noqa: E402
from backend.plugins.stream_carver import _carve_annexb_run  # noqa: E402
from backend.reconstructor import label_all  # noqa: E402
from backend.test_images.gen_test_image import build_gpt_header_image, build_honeywell_stream  # noqa: E402


def main() -> None:
    if not PERSON_A.is_file() or not PERSON_B.is_file():
        print(f"Missing test photos at {PERSON_A} and {PERSON_B}.")
        sys.exit(1)

    stream = build_h264_stream(PERSON_A)
    tmp = SCRATCH / "hw_source.h264"
    tmp.write_bytes(stream)
    with open(tmp, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        spans, _ = _carve_annexb_run(mm, stream.find(b"\x00\x00\x01\x67"), len(stream))
    payloads = [(stream[a:b], key) for a, b, _t, key in spans]
    print(f"real H.264: {len(stream):,} bytes, {len(payloads)} pictures")

    base = int(datetime(2025, 11, 26, 21, 48, 19, tzinfo=timezone.utc).timestamp()) * 1_000_000
    ch_a = build_honeywell_stream(payloads, base, width=480, height=360)
    ch_b = build_honeywell_stream(payloads, base + 30_000, width=480, height=360)   # overlaps channel A in time

    img = build_gpt_header_image(first_lba=40, total_sectors=64)
    img += b"\xCC" * 4096 + os.urandom(2000).replace(b"\x82\x80\x01\x00", b"\x00\x00\x00\x00") \
        + ch_a + b"\xCC" * 4096 + ch_b + b"\xCC" * 4096
    dd = SCRATCH / "sample_honeywell_gpt_real_video.dd"
    dd.write_bytes(bytes(img))
    print(f"disk image: {dd} ({len(img):,} bytes)")

    with EvidenceImage.open(dd) as image:
        plugin = HoneywellPlugin()
        conf = plugin.detect(image)
        print(f"detect() = {conf}  (scan threshold {MIN_PLUGIN_CONFIDENCE})")
        assert conf >= MIN_PLUGIN_CONFIDENCE

        frames, note = plugin.carve(image)
        print(f"carve(): {len(frames)} record(s) - {note}")
        segs = label_all(frames, "e2e-honeywell")
        print(f"label_all(): {len(segs)} segment(s)")
        assert len(segs) == 2, "two overlapping channel streams must stay two segments"
        assert all(s.status == SegmentStatus.UNCERTAIN for s in segs)

        for i, seg in enumerate(segs):
            recovered = b"".join(bytes(image.mm[o.start:o.end]) for o in seg.disk_offsets)
            assert recovered == stream, f"segment {i}: payload not byte-identical to the embedded video"
            print(f"segment {i}: byte-exact, {seg.frame_count} frames, "
                  f"{seg.start_time.isoformat()} -> {seg.end_time.isoformat()}")
            seg, detail = export_segment(image.mm, seg, SCRATCH / f"export_honeywell_{i}")
            assert "error" not in detail, detail
            ok, info = ffprobe_check(Path(seg.export_path))
            assert ok, info
            assert seg.status == SegmentStatus.PARTIAL
            segs[i] = seg

    export = segs[0].export_path
    res = detect_faces_in_video(export, frame_stride=1)
    print(res.summary)
    assert res.faces_detected

    ref_same = extract_embedding_from_image_bytes(PERSON_A.read_bytes())
    ref_diff = extract_embedding_from_image_bytes(PERSON_B.read_bytes())
    recs = index_faces_for_search(export, frame_stride=1)
    same = max(cosine_similarity(ref_same, r.embedding) for r in recs)
    diff = max(cosine_similarity(ref_diff, r.embedding) for r in recs)
    print(f"face search: same person max={same:.4f}   different person max={diff:.4f}")
    assert same > diff

    print("\n" + "#" * 70 + "\nALL HONEYWELL STEPS PASSED\n" + "#" * 70)


if __name__ == "__main__":
    main()
