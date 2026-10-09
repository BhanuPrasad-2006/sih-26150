"""
test_hevc_carving.py — Standards-based H.265 / HEVC stream carving and emulation byte stripping.

Verifies:
  - ITU-T H.264/H.265 emulation prevention byte (0x03) stripping.
  - Recovery of raw H.265 (HEVC) Annex B streams embedded in raw disk images with decoys.
  - Identification of VPS, SPS, PPS, and Keyframes (IDR / CRA).
  - Remuxing carved HEVC streams to MP4 container and decoding via ffprobe.
"""

import os
import subprocess
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.models import SegmentStatus
from backend.plugins.stream_carver import (
    carve_standard_streams,
    strip_emulation_prevention_bytes,
)
from backend.reconstructor import label_all

pytestmark = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)


def test_strip_emulation_prevention_bytes():
    # 0x00000300 -> 0x000000
    # 0x00000301 -> 0x000001
    # 0x00000302 -> 0x000002
    # 0x00000303 -> 0x000003
    raw_payload = b"\x01\x02\x00\x00\x03\x01\xAA\xBB\x00\x00\x03\x00\xCC\x00\x00\x03\x03\xDD"
    expected = b"\x01\x02\x00\x00\x01\xAA\xBB\x00\x00\x00\xCC\x00\x00\x03\xDD"
    assert strip_emulation_prevention_bytes(raw_payload) == expected

    # Plain payload without emulation byte remains untouched
    plain = b"\x40\x01\x0C\x01\xFF\xAA\xBB"
    assert strip_emulation_prevention_bytes(plain) == plain


def _encode_hevc(path: str, duration: int = 1) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
            "-c:v", "libx265", "-pix_fmt", "yuv420p", "-f", "hevc", path
        ],
        check=True,
    )
    return Path(path).read_bytes()


@pytest.fixture(scope="module")
def raw_hevc_bytes(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("hevc") / "test_stream.hevc")
    return _encode_hevc(out)


def test_carve_hevc_stream_from_disk_image(tmp_path, raw_hevc_bytes):
    # Construct a disk image with decoys, noise, and the embedded HEVC bitstream
    noise_before = os.urandom(1024)
    # A decoy start code with invalid temporal_id_plus1 = 0
    decoy_vps = b"\x00\x00\x01\x40\x00\xFF\xEE\xDD"
    noise_middle = os.urandom(2048)
    tail_filler = b"\xFF" * 1024

    image_data = noise_before + decoy_vps + noise_middle + raw_hevc_bytes + tail_filler

    img_file = tmp_path / "evidence_dump.dd"
    img_file.write_bytes(image_data)

    with EvidenceImage.open(img_file) as img:
        frames, note = carve_standard_streams(img, "generic")
        assert len(frames) > 0, f"Expected carved frames, got note: {note}"
        assert "H.265/HEVC Annex B run(s)" in note

        # Check that we carved at least one keyframe
        keyframes = [f for f in frames if f.is_keyframe]
        assert len(keyframes) >= 1

        # Reconstruct into segment
        segments = label_all(frames, "ev-hevc-01")
        assert len(segments) >= 1

        # Export and verify MP4 remuxing
        export_dir = tmp_path / "exports"
        seg = segments[0]
        updated_seg, detail = export_segment(img.mm, seg, export_dir)

        assert updated_seg.status == SegmentStatus.PARTIAL
        assert updated_seg.export_path is not None
        assert Path(updated_seg.export_path).exists()
        assert Path(updated_seg.export_path).suffix == ".mp4"
        assert updated_seg.sha256 is not None
        assert detail.get("ffprobe_valid") is True
        assert detail["ffprobe"]["streams"][0]["codec_name"] == "hevc"
