"""
e2e_hikvision_real_video_verification.py — Manual end-to-end verification for the
Hikvision plugin, NOT collected by pytest (needs ffmpeg and two local face photos).

Mirrors e2e_real_video_verification.py (Dahua). Builds a REAL H.264 video of a
face, embeds it in a Hikvision-style disk image (master sector at 0x200 + noise
+ decoys) in two container forms, and runs the actual pipeline:

    detect -> carve -> reconstruct -> byte-fidelity check -> export ->
    ffprobe -> face detection -> face search (same person vs different person)

Forms tested:
  * raw H.264 Annex B stream   (ITU-T H.264 Annex B)
  * MPEG program stream        (ISO/IEC 13818-1; FFmpeg's mpeg.c confirms
                                Hikvision video files are MPEG-PS)

What this does NOT prove: that a REAL Hikvision disk stores video this way in
its data blocks (the HIKB-TREE / block layout is unverified). It proves the
carver recovers standards-conformant streams byte-exactly and that they decode.

Usage: see e2e_real_video_verification.py (same two photos in ./_scratch/).
  python backend/tests/manual/e2e_hikvision_real_video_verification.py
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from e2e_real_video_verification import FRAMES_DIR, PERSON_A, PERSON_B, SCRATCH, build_h264_stream  # noqa: E402

from backend.acquisition import EvidenceImage  # noqa: E402
from backend.exporter import export_segment, ffprobe_check  # noqa: E402
from backend.face_detection import detect_faces_in_video  # noqa: E402
from backend.face_search import (  # noqa: E402
    cosine_similarity,
    extract_embedding_from_image_bytes,
    index_faces_for_search,
)
from backend.models import SegmentStatus  # noqa: E402
from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET  # noqa: E402
from backend.plugins.hikvision import HikvisionPlugin  # noqa: E402
from backend.reconstructor import label_all  # noqa: E402


def encode_ps() -> bytes:
    out = SCRATCH / "stream.mpg"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "10", "-i", str(FRAMES_DIR / "f%04d.png"),
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "mpeg", str(out)],
        check=True,
    )
    return out.read_bytes()


def decoys() -> bytes:
    """Bytes that resemble stream openings but aren't real streams."""
    rnd = os.urandom(3000)
    return (
        b"\xCC" * 512
        + b"\x00\x00\x01\x67\x42\x00\x1e" + rnd      # SPS-like start, no PPS/slice
        + b"\x00\x00\x01\xBA\x44\x00\x04\x00\x04\x01" + rnd  # pack-like start, bad chain
        + b"\x00\x00\x01\x67" + b"\x64" + rnd          # SPS start code, bogus rest
        + b"\xCC" * 512
    )


def build_image(payload: bytes) -> bytes:
    buf = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    buf += HIKV_MASTER_SECTOR_MAGIC + b"\x00" * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    buf += decoys() + b"\xCC" * 4096 + payload + b"\xCC" * 4096 + decoys()
    return bytes(buf)


def run_variant(name: str, payload: bytes) -> None:
    print("\n" + "=" * 70)
    print(f"VARIANT: {name}  ({len(payload):,} payload bytes)")
    print("=" * 70)
    dd = SCRATCH / f"sample_hikvision_{name}.dd"
    dd.write_bytes(build_image(payload))

    with EvidenceImage.open(dd) as img:
        plugin = HikvisionPlugin()
        conf = plugin.detect(img)
        print(f"detect() confidence: {conf}")
        assert conf == 1.0

        frames, note = plugin.carve(img)
        print(f"carve(): {len(frames)} unit(s) — {note}")
        segs = label_all(frames, "e2e-hikvision")
        print(f"label_all(): {len(segs)} segment(s)")
        assert len(segs) == 1, f"expected exactly 1 segment (decoys must be rejected), got {len(segs)}"
        seg = segs[0]
        assert seg.status == SegmentStatus.UNCERTAIN, "must start UNCERTAIN until decode-validated"

        recovered = b"".join(bytes(img.mm[o.start:o.end]) for o in seg.disk_offsets)
        print(f"recovered {len(recovered):,} bytes vs original {len(payload):,}")
        assert recovered == payload, "recovered bytes are not byte-identical to the embedded stream"
        print("byte-exact: recovered bytes == embedded stream")

        out_dir = SCRATCH / f"export_{name}"
        seg, detail = export_segment(img.mm, seg, out_dir)
        assert "error" not in detail, detail
        ok, info = ffprobe_check(Path(seg.export_path))
        print(f"exported: {seg.export_path}  ffprobe_valid={ok}  status={seg.status}")
        assert ok, info
        assert seg.status == SegmentStatus.PARTIAL, "decode-validated export should be PARTIAL, never COMPLETE"

    res = detect_faces_in_video(seg.export_path, frame_stride=1)
    print(res.summary)
    assert res.faces_detected

    ref_same = extract_embedding_from_image_bytes(PERSON_A.read_bytes())
    ref_diff = extract_embedding_from_image_bytes(PERSON_B.read_bytes())
    recs = index_faces_for_search(seg.export_path, frame_stride=1)
    same = max(cosine_similarity(ref_same, r.embedding) for r in recs)
    diff = max(cosine_similarity(ref_diff, r.embedding) for r in recs)
    print(f"face search: same person max={same:.4f}   different person max={diff:.4f}")
    assert same > diff


def negative_test() -> None:
    print("\n" + "=" * 70)
    print("NEGATIVE: image with a valid master sector but NO real stream")
    print("=" * 70)
    dd = SCRATCH / "sample_hikvision_no_stream.dd"
    dd.write_bytes(build_image(b""))
    with EvidenceImage.open(dd) as img:
        frames, note = HikvisionPlugin().carve(img)
        print(f"carve(): {len(frames)} unit(s)")
        assert len(frames) == 0, "decoys/noise must not be reported as video"


def main() -> None:
    if not PERSON_A.is_file() or not PERSON_B.is_file():
        print(f"Missing test photos at {PERSON_A} and {PERSON_B} (see e2e_real_video_verification.py).")
        sys.exit(1)
    raw = build_h264_stream(PERSON_A)
    ps = encode_ps()
    run_variant("raw_h264", raw)
    run_variant("mpeg_ps", ps)
    negative_test()
    print("\n" + "#" * 70)
    print("ALL HIKVISION STEPS PASSED")
    print("#" * 70)


if __name__ == "__main__":
    main()
