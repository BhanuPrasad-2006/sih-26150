"""
test_hikvision_carving.py — Standards-based Hikvision stream carving.

Uses REAL ffmpeg-encoded video (testsrc) wrapped as raw H.264 Annex B and as an
MPEG program stream, embedded in a disk image with a valid Hikvision master
sector, noise and decoys. Verifies byte-exact recovery, false-positive
rejection, contiguity-based segmentation, and decode-gated status labelling.

Skipped when ffmpeg is unavailable. See docs/format_sheets/hikvision.md §4.
"""

import os
import subprocess
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.models import SegmentStatus
from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET
from backend.plugins.hikvision import HikvisionPlugin
from backend.reconstructor import label_all

pytestmark = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)


def _encode(fmt: str, path: str, duration: int = 1) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", fmt, path],
        check=True,
    )
    return Path(path).read_bytes()


def _decoys() -> bytes:
    rnd = os.urandom(2000)
    return (
        b"\xCC" * 300
        + b"\x00\x00\x01\x67\x42\x00\x1e" + rnd
        + b"\x00\x00\x01\xBA\x44\x00\x04\x00\x04\x01" + rnd
        + b"\x00\x00\x01\x67\x64" + rnd
        + b"\xCC" * 300
    )


def _image(*payloads: bytes) -> bytes:
    buf = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    buf += HIKV_MASTER_SECTOR_MAGIC + b"\x00" * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    buf += _decoys() + b"\xCC" * 2048
    for p in payloads:
        buf += p + b"\xCC" * 2048 + _decoys() + b"\xCC" * 2048
    return bytes(buf)


def _recovered(img, seg) -> bytes:
    return b"".join(bytes(img.mm[o.start:o.end]) for o in seg.disk_offsets)


@pytest.fixture(scope="module")
def raw_h264(tmp_path_factory):
    return _encode("h264", str(tmp_path_factory.mktemp("h") / "a.h264"))


@pytest.fixture(scope="module")
def mpeg_ps(tmp_path_factory):
    return _encode("mpeg", str(tmp_path_factory.mktemp("p") / "a.mpg"))


def _carve_segments(path):
    with EvidenceImage.open(path) as img:
        frames, note = HikvisionPlugin().carve(img)
        segs = label_all(frames, "ev")
        return img, frames, segs, note


@pytest.mark.parametrize("fixture_name", ["raw_h264", "mpeg_ps"])
def test_stream_recovered_byte_exact_despite_decoys(request, temp_dir, fixture_name):
    payload = request.getfixturevalue(fixture_name)
    path = os.path.join(temp_dir, f"{fixture_name}.dd")
    Path(path).write_bytes(_image(payload))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 1, "decoys must not produce extra segments"
        assert _recovered(img, segs[0]) == payload


def test_h264_frame_count_matches_encoded_frames(temp_dir, raw_h264):
    path = os.path.join(temp_dir, "count.dd")
    Path(path).write_bytes(_image(raw_h264))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        assert len(frames) == 10  # testsrc duration=1 at 10 fps, one slice per picture
        assert frames[0].is_keyframe is True


def test_separate_streams_become_separate_segments(temp_dir, raw_h264, mpeg_ps):
    path = os.path.join(temp_dir, "two.dd")
    Path(path).write_bytes(_image(raw_h264, mpeg_ps))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 2
        assert {_recovered(img, s) for s in segs} == {raw_h264, mpeg_ps}


@pytest.mark.parametrize("fixture_name", ["raw_h264", "mpeg_ps"])
def test_export_is_partial_never_complete(request, temp_dir, fixture_name):
    payload = request.getfixturevalue(fixture_name)
    path = os.path.join(temp_dir, f"exp_{fixture_name}.dd")
    Path(path).write_bytes(_image(payload))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        seg = label_all(frames, "ev")[0]
        assert seg.status == SegmentStatus.UNCERTAIN  # before any decode validation
        seg, detail = export_segment(img.mm, seg, Path(temp_dir) / f"out_{fixture_name}")
        assert "error" not in detail
        assert detail["ffprobe_valid"] is True
        assert seg.status == SegmentStatus.PARTIAL


def test_no_real_stream_yields_nothing(temp_dir):
    path = os.path.join(temp_dir, "decoys_only.dd")
    Path(path).write_bytes(_image())
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        assert frames == []


def test_random_data_yields_nothing(temp_dir):
    path = os.path.join(temp_dir, "random.dd")
    Path(path).write_bytes(os.urandom(256 * 1024))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        assert frames == []
