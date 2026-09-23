"""
e2e_real_video_verification.py — Manual end-to-end verification, NOT collected
by pytest (no `test_` prefix — needs ffmpeg on PATH and two local face photos
that aren't part of this repo).

Builds a REAL H.264-encoded video containing a human face, embeds it inside a
genuine DHAV frame (matching the real Dahua/FFmpeg format — see
docs/format_sheets/dahua.md), writes it as a synthetic .dd disk image, and
runs it through the actual detection -> carving -> reconstruction -> export
-> face detection -> face search pipeline exactly as the deployed app would.

This proves (or disproves) end-to-end functionality with REAL video content,
not just structural placeholder bytes like gen_test_image.py's synthetic
images use — it's what caught the DHAV frame-type/header bugs fixed 2026-09.

Usage:
  1. Put two DIFFERENT face photos at the paths below. Use AI-generated faces
     (e.g. thispersondoesnotexist.com) — never a real, identifiable person —
     consistent with this project's synthetic-data-only testing policy.
  2. python backend/tests/manual/e2e_real_video_verification.py
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffprobe_check
from backend.face_detection import detect_faces_in_video
from backend.face_search import (
    cosine_similarity,
    extract_embedding_from_image_bytes,
    index_faces_for_search,
)
from backend.plugins.constants import DHAV_TRAILER_SIZE, MIN_PLUGIN_CONFIDENCE
from backend.plugins.dahua import DahuaPlugin
from backend.reconstructor import label_all
from backend.test_images.gen_test_image import make_dhav_frame

SCRATCH = Path(__file__).parent / "_scratch"
FRAMES_DIR = SCRATCH / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)
PERSON_A = SCRATCH / "person_a.jpg"  # the "reference"/same-person photo
PERSON_B = SCRATCH / "person_b.jpg"  # a different person, for the negative case


def build_h264_stream(face_jpg: Path, num_frames: int = 40, size=(480, 360)) -> bytes:
    """Encode a real H.264 elementary stream showing a face, via ffmpeg + libx264."""
    face = cv2.imread(str(face_jpg))
    face = cv2.resize(face, size)

    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()
    for i in range(num_frames):
        # Tiny jitter so it's not a perfectly static image (more video-like).
        dx, dy = (i % 5) - 2, (i % 3) - 1
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        frame = cv2.warpAffine(face, m, size, borderMode=cv2.BORDER_REPLICATE)
        cv2.imwrite(str(FRAMES_DIR / f"f{i:04d}.png"), frame)

    h264_path = SCRATCH / "stream.h264"
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", "10",
            "-i", str(FRAMES_DIR / "f%04d.png"),
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-f", "h264", str(h264_path),
        ],
        check=True, capture_output=True, text=True,
    )
    return h264_path.read_bytes()


def make_real_dhav_frame(payload: bytes, channel: int, seq: int, ts_seconds: int) -> bytes:
    """
    Wrap a REAL H.264 elementary stream in a genuine DHAV frame using the
    corrected, FFmpeg-source-verified format (gen_test_image.make_dhav_frame).

    Includes extension TLV type 0x81 (video codec) so FFmpeg's real dhav
    demuxer can identify the stream as H.264 (codec byte 0x8) — without this,
    parse_ext() leaves dhav->video_codec at 0 and the demuxer can't set up
    the video stream's codec_id.
    """
    ext_data = bytes([
        0x80, 0x00, 480 // 8, 360 // 8,   # width/height (8px units)
        0x81, 0x00, 0x08, 10,             # video_codec=0x8 (H.264), frame_rate=10
    ])
    frame = bytearray(make_dhav_frame(
        channel=channel,
        seq=seq,
        ts_seconds=ts_seconds,
        payload_size=len(payload),
        ext_data=ext_data,
    ))
    header_size = len(frame) - len(payload) - DHAV_TRAILER_SIZE
    frame[header_size : header_size + len(payload)] = payload
    return bytes(frame)


def main():
    if not PERSON_A.is_file() or not PERSON_B.is_file():
        print(f"Missing test photos. Place two DIFFERENT, non-real (AI-generated) "
              f"face photos at:\n  {PERSON_A}\n  {PERSON_B}\nthen re-run.")
        sys.exit(1)

    print("=" * 70)
    print("STEP 1: Encode a real H.264 video containing a human face")
    print("=" * 70)
    h264_bytes = build_h264_stream(PERSON_A)
    print(f"Encoded real H.264 stream: {len(h264_bytes):,} bytes")

    print()
    print("=" * 70)
    print("STEP 2: Wrap it in a genuine DHAV frame + build a synthetic disk image")
    print("=" * 70)
    import time as _time
    now = int(_time.time())
    dhav_frame = make_real_dhav_frame(h264_bytes, channel=0, seq=0, ts_seconds=now)
    disk_image = (b"\xCC" * 1024) + dhav_frame + (b"\xCC" * 1024)
    dd_path = SCRATCH / "sample_dahua_with_face_REALVIDEO.dd"
    dd_path.write_bytes(disk_image)
    print(f"Disk image written: {dd_path} ({len(disk_image):,} bytes)")

    print()
    print("=" * 70)
    print("STEP 3: Run the REAL app pipeline — detect, carve, reconstruct")
    print("=" * 70)
    with EvidenceImage.open(dd_path) as img:
        plugin = DahuaPlugin()
        confidence = plugin.detect(img)
        print(f"DahuaPlugin.detect() confidence: {confidence:.2f} "
              f"(threshold to scan: {MIN_PLUGIN_CONFIDENCE})")
        assert confidence >= MIN_PLUGIN_CONFIDENCE, "Detection FAILED — would not have triggered a scan"

        frames, note = plugin.carve(img)
        print(f"carve(): {len(frames)} frame(s) found — {note}")
        assert len(frames) == 1, f"Expected exactly 1 carved DHAV frame, got {len(frames)}"

        segments = label_all(frames, evidence_id="e2e-test-evidence")
        print(f"label_all(): {len(segments)} segment(s)")
        assert len(segments) == 1
        seg = segments[0]
        print(f"Segment: camera={seg.camera} status={seg.status} frame_count={seg.frame_count} "
              f"disk_offsets={len(seg.disk_offsets)}")
        assert len(seg.disk_offsets) == 1, "Frame was filtered out as a placeholder — export would be empty"

        print()
        print("=" * 70)
        print("STEP 4: Export to MP4 via the REAL exporter (ffmpeg dhav demuxer)")
        print("=" * 70)
        out_dir = SCRATCH / "export"
        out_dir.mkdir(exist_ok=True)
        seg, detail = export_segment(img.mm, seg, out_dir)
        print("Export detail:", {k: v for k, v in detail.items() if k != "ffprobe"})
        assert "error" not in detail, f"EXPORT FAILED: {detail.get('error')}"
        assert seg.export_path and Path(seg.export_path).is_file(), "No export file produced"
        print(f"Exported: {seg.export_path} ({Path(seg.export_path).stat().st_size:,} bytes)")

        probe_ok, probe_info = ffprobe_check(Path(seg.export_path))
        print(f"ffprobe valid decodable stream: {probe_ok}")
        assert probe_ok, f"ffprobe could not decode the exported file: {probe_info}"

    print()
    print("=" * 70)
    print("STEP 5: AI-Based Face Detection on the recovered/exported video")
    print("=" * 70)
    face_result = detect_faces_in_video(seg.export_path, frame_stride=1)
    print(face_result.summary)
    assert face_result.faces_detected, "FACE DETECTION FAILED on recovered video"
    assert face_result.frames_with_faces > 0

    print()
    print("=" * 70)
    print("STEP 6: Face search — does the SAME person's photo match?")
    print("=" * 70)
    ref_same = extract_embedding_from_image_bytes(PERSON_A.read_bytes())
    ref_diff = extract_embedding_from_image_bytes(PERSON_B.read_bytes())
    assert ref_same is not None and ref_diff is not None, "Could not extract reference embeddings"

    video_records = index_faces_for_search(seg.export_path, frame_stride=1)
    print(f"Indexed {len(video_records)} face embedding(s) from the recovered video")
    assert len(video_records) > 0

    same_scores = [cosine_similarity(ref_same, r.embedding) for r in video_records]
    diff_scores = [cosine_similarity(ref_diff, r.embedding) for r in video_records]
    print(f"Similarity vs SAME person (person_a):      max={max(same_scores):.4f}  avg={sum(same_scores)/len(same_scores):.4f}")
    print(f"Similarity vs DIFFERENT person (person_b): max={max(diff_scores):.4f}  avg={sum(diff_scores)/len(diff_scores):.4f}")

    assert max(same_scores) > max(diff_scores), (
        "Face search FAILED to discriminate: the different person scored higher than the actual match"
    )

    print()
    print("#" * 70)
    print("ALL STEPS PASSED — full pipeline works end-to-end with real video + a real face.")
    print("#" * 70)


if __name__ == "__main__":
    main()
