"""Borrowing missing H.264 parameter sets (SPS/PPS) for a Dahua piece whose first keyframe lost them."""

import shutil
import subprocess
from pathlib import Path

import pytest

from backend import parameter_sets as ps
from backend.exporter import export_segment
from backend.models import DiskOffset, Segment
from backend.test_images.gen_test_image import make_dhav_frame
from backend.tests import test_dahua_dhfs as D

NEED_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg needed")

SC = b"\x00\x00\x00\x01"


def _nal(t, body=b"\x11\x22\x33"):
    return SC + bytes([0x60 | t]) + body


# ── the byte-level helpers ────────────────────────────────────────────────────

def test_nals_are_split_and_typed():
    stream = _nal(7) + _nal(8) + _nal(5, b"\xaa" * 10) + _nal(1, b"\xbb" * 5)
    assert [ps.nal_type(n) for n in ps.split_nals(stream)] == [7, 8, 5, 1]


def test_sps_pps_pair_is_found_and_normalised():
    stream = b"\x00\x00\x01" + bytes([0x67, 1, 2]) + b"\x00\x00\x01" + bytes([0x68, 3]) + _nal(5)
    sps, pps = ps.find_sps_pps(stream)
    assert sps == SC + bytes([0x67, 1, 2]) and pps == SC + bytes([0x68, 3])
    assert ps.find_sps_pps(_nal(5) + _nal(1)) is None


def test_a_keyframe_without_parameter_sets_is_detected():
    assert ps.first_idr_lacks_parameter_sets(_nal(1) + _nal(5) + _nal(1)) is True
    assert ps.first_idr_lacks_parameter_sets(_nal(7) + _nal(8) + _nal(5)) is False
    assert ps.first_idr_lacks_parameter_sets(_nal(1) + _nal(1)) is False          # no keyframe: nothing a header can fix


def test_frames_before_the_first_keyframe_are_dropped_but_its_own_settings_are_kept():
    stream = _nal(1, b"\x01") + _nal(1, b"\x02") + _nal(7) + _nal(8) + _nal(5, b"\x03")
    assert ps.drop_before_first_idr(stream).startswith(_nal(7))


def test_repair_needs_a_keyframe_missing_its_settings():
    def dhav(payload):
        return bytes(make_dhav_frame(0, 0, 0, ts_ms=0, frame_type=0xFD, payload_size=len(payload), ext_data=D._EXT)[:-8 - len(payload)]
                     ) + payload + b"dhav" + (24 + len(D._EXT) + len(payload) + 8).to_bytes(4, "little")

    donor = (_nal(7, b"\x77"), _nal(8, b"\x88"))
    with_settings = dhav(_nal(7) + _nal(8) + _nal(5))
    assert ps.repair_stream(with_settings, donor) is None                          # already has its own: leave alone
    assert ps.repair_stream(dhav(_nal(1)), donor) is None                          # no keyframe at all: nothing to repair
    fixed = ps.repair_stream(dhav(_nal(5, b"\xcc" * 8)), donor)
    assert fixed.startswith(donor[0] + donor[1]) and _nal(5, b"\xcc" * 8) in fixed


# ── end to end with real video ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def two_pieces(tmp_path_factory):
    """A 3 s clip with a keyframe every second, as DHAV: piece A intact, piece B = a later run of frames whose
    keyframe has had its SPS/PPS stripped (as if the copy in front of it was overwritten)."""
    d = tmp_path_factory.mktemp("params")
    out = d / "clip.h264"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-g", "10", "-bf", "0",
                    "-f", "h264", str(out)], check=True)
    pictures = D._split_pictures(out.read_bytes())
    assert sum(1 for _, k in pictures if k) >= 3

    def frames(pics, strip):
        blob = bytearray()
        for i, (pic, key) in enumerate(pics):
            if strip and key:
                pic = b"".join(n for n in ps.split_nals(pic) if ps.nal_type(n) not in (7, 8))
            f = bytearray(make_dhav_frame(0, i, 1000 + i // 10, ts_ms=(i % 10) * 100, frame_type=0xFD if key else 0xFC,
                                          payload_size=len(pic), ext_data=D._EXT))
            hdr = len(f) - len(pic) - 8
            f[hdr:hdr + len(pic)] = pic
            blob += f
        return bytes(blob)

    a = frames(pictures[:10], strip=False)                    # first second: intact, has SPS/PPS
    b = frames(pictures[10:20], strip=True)                   # second second: keyframe lost its settings
    disk = a + b
    seg = lambda start, end, cam: Segment(evidence_id="e", camera=cam, disk_offsets=[DiskOffset(start=start, end=end)])   # noqa: E731
    return disk, seg(0, len(a), 0), seg(len(a), len(a) + len(b), 0)


@NEED_FFMPEG
def test_a_piece_without_settings_does_not_play_on_its_own(two_pieces, tmp_path):
    disk, _, piece_b = two_pieces
    _, detail = export_segment(disk, piece_b, tmp_path)               # no donor offered
    assert detail["ffprobe_valid"] is False


@NEED_FFMPEG
def test_borrowed_settings_make_it_play_and_the_note_says_so(two_pieces, tmp_path):
    disk, piece_a, piece_b = two_pieces

    def donor():
        return ps.find_sps_pps(b"".join(ps.dhav_video_payloads(disk[piece_a.disk_offsets[0].start:piece_a.disk_offsets[0].end])))

    seg, detail = export_segment(disk, piece_b, tmp_path, donor)
    assert detail["ffprobe_valid"] is True and detail["parameter_sets_borrowed"] is True
    assert "borrowed from another piece" in seg.notes
    assert Path(seg.export_path).suffix == ".mp4"
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", seg.export_path, "-f", "null", "-"], capture_output=True, text=True)
    assert decode.returncode == 0 and not decode.stderr.strip()       # the borrowed settings decode every frame cleanly


@NEED_FFMPEG
def test_an_intact_piece_is_never_touched_by_the_repair(two_pieces, tmp_path):
    disk, piece_a, _ = two_pieces
    called = []
    seg, detail = export_segment(disk, piece_a, tmp_path, lambda: called.append(1))
    assert detail["ffprobe_valid"] is True and "parameter_sets_borrowed" not in detail and not called
