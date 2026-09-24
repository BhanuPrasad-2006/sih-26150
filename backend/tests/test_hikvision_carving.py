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


_PACK_HEADER = bytes.fromhex("000001BA" "44000400" "0401" "000003F8")          # valid MPEG-2 pack header, 14 bytes
_PSM = bytes.fromhex("000001BC" "000E") + bytes.fromhex("E1FF0000" "00041BE0" "00000000" "0000")   # program stream map


def _han_fig4_block(h264: bytes) -> tuple[bytes, bytes]:
    """
    Lay real H.264 out as Han 2015 Fig. 4 shows a Hikvision data block: `00 00 01 BA` before every
    picture and `00 00 01 BC` before keyframes, ahead of the picture's NAL units. Returns
    (block_bytes, expected_recovery) — the carver starts at the first SPS, so anything before it
    (the first BA/BC) is not part of the recovered stream.
    """
    import mmap
    import tempfile

    from backend.plugins.stream_carver import _carve_annexb_run

    with tempfile.NamedTemporaryFile(delete=False, suffix=".h264") as tf:
        tf.write(h264)
    with open(tf.name, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        spans, _ = _carve_annexb_run(mm, h264.find(b"\x00\x00\x01\x67"), len(h264))
    os.unlink(tf.name)

    block = bytearray()
    first_payload_at = None
    for start, stop, _t, key in spans:
        block += _PACK_HEADER + (_PSM if key else b"")
        if first_payload_at is None:
            first_payload_at = len(block)
        block += h264[start:stop]
    return bytes(block), bytes(block[first_payload_at:])


def test_han_fig4_ba_bc_headers_between_pictures_do_not_break_carving(temp_dir, raw_h264):
    block, expected = _han_fig4_block(raw_h264)
    path = os.path.join(temp_dir, "han_fig4.dd")
    Path(path).write_bytes(_image(block))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 1
        assert _recovered(img, segs[0]) == expected          # byte-exact, headers preserved
        assert len(frames) == 10                             # one unit per picture, as without the headers
        seg, detail = export_segment(img.mm, segs[0], Path(temp_dir) / "out_fig4")
        assert "error" not in detail and detail["ffprobe_valid"] is True


def test_random_data_yields_nothing(temp_dir):
    path = os.path.join(temp_dir, "random.dd")
    Path(path).write_bytes(os.urandom(256 * 1024))
    with EvidenceImage.open(path) as img:
        frames, _ = HikvisionPlugin().carve(img)
        assert frames == []
