"""Frames that straddle interleaved clusters are put back together, only when the bytes are pinned down, and never guessed."""

import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.models import RawFrame
from backend.plugins.constants import DHAV_TRAILER_MAGIC
from backend.plugins.dahua_stitch import OpenFrame, stitch

TOOLS = Path(__file__).resolve().parents[2] / "tools"
NEED_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg needed")
T0 = datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


# ── the stitcher on hand-made memory (no ffmpeg) ──────────────────────────────

CS = 128
POS = CS - 40                                            # each test frame starts 40 bytes before the end of cluster 0
PART = SimpleNamespace(video_area=0, cluster_size=CS, desc_count=12)


def _frame(channel, seq, total):
    """A fake DHAV frame: marker + channel + sequence + total + trailer, payload of varied bytes."""
    body = bytearray((seq * 31 + i * 7) % 251 for i in range(total))         # varied, like compressed video
    body[0:4] = b"DHAV"
    body[6] = channel
    struct.pack_into("<I", body, 8, seq)
    struct.pack_into("<I", body, 12, total)
    body[total - 8: total - 4] = DHAV_TRAILER_MAGIC
    struct.pack_into("<I", body, total - 4, total)
    return bytes(body)


def _parse(mm, pos, size):
    """Stand-in for dahua._parse_dhav_header on the fake frames."""
    if pos + 16 > size or bytes(mm[pos:pos + 4]) != b"DHAV":
        return None
    return OpenFrame(pos=pos, channel=mm[pos + 6], sequence=struct.unpack_from("<I", mm, pos + 8)[0],
                     total=struct.unpack_from("<I", mm, pos + 12)[0], timestamp=T0, frame_type=0xFC, is_keyframe=False)


def _layout(chunks):
    """chunks: {cluster index: bytes}; returns the disk bytes."""
    disk = bytearray(CS * PART.desc_count)
    for idx, data in chunks.items():
        assert len(data) <= CS, (idx, len(data))
        disk[idx * CS: idx * CS + len(data)] = data
    return bytes(disk)


def _open_from(seq, total, channel=0):
    return OpenFrame(pos=POS, channel=channel, sequence=seq, total=total, timestamp=T0, frame_type=0xFC, is_keyframe=False)


def _rebuilt(disk, fr):
    return b"".join(disk[a:b] for a, b in [(fr.disk_offset, fr.disk_offset + fr.frame_size), *fr.extra_ranges])


def _first_cluster(frame):
    return b"\x11" * POS + frame[:40]


def test_a_frame_split_over_two_clusters_is_put_back_by_trailer_and_continuation():
    f1, f2 = _frame(0, 1, 100), _frame(0, 2, 30)         # f1 continues in cluster 3 (clusters 1-2 belong to another camera)
    other = bytes((i * 11 + 3) % 251 for i in range(CS))
    disk = _layout({0: _first_cluster(f1), 1: other, 2: other, 3: f1[40:] + f2})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 100)], _parse)
    assert stats.stitched == 1 and len(frames) == 1
    assert _rebuilt(disk, frames[0]) == f1                # exactly the original frame, byte for byte


def test_a_frame_needing_a_middle_cluster_is_stitched_when_that_cluster_is_unambiguous():
    f1, f2 = _frame(0, 1, 260), _frame(0, 2, 30)         # 40 in cluster 0, a whole cluster in the middle, 92 in the last
    disk = _layout({0: _first_cluster(f1), 1: f1[40:40 + CS], 4: f1[40 + CS:] + f2})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 260)], _parse)
    assert stats.stitched == 1
    assert _rebuilt(disk, frames[0]) == f1


def test_an_ambiguous_middle_cluster_is_never_guessed():
    f1, f2 = _frame(0, 1, 260), _frame(0, 2, 30)
    # two header-less clusters (1 and 2) could each be the middle piece: the stitcher must refuse rather than pick one
    disk = _layout({0: _first_cluster(f1), 1: f1[40:40 + CS], 2: bytes((i * 13 + 5) % 251 for i in range(CS)), 4: f1[40 + CS:] + f2})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 260)], _parse)
    assert frames == [] and stats.ambiguous == 1 and stats.stitched == 0


def test_nothing_is_stitched_when_the_continuation_was_overwritten():
    f1, f2 = _frame(0, 1, 100), _frame(0, 2, 30)
    tail = bytearray(f1[40:] + f2)
    tail[(100 - 40) - 8:(100 - 40) - 4] = b"XXXX"          # the frame's trailer marker in the continuation is gone
    disk = _layout({0: _first_cluster(f1), 3: bytes(tail)})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 100)], _parse)
    assert frames == [] and stats.unresolved == 1


def test_a_continuation_followed_by_another_camera_loses_to_one_followed_by_the_same_camera():
    f1 = _frame(0, 1, 100)
    other_next = _frame(5, 2, 30)                          # right trailer, but the frame after it is camera 5's
    same_next = _frame(0, 2, 30)
    disk = _layout({0: _first_cluster(f1), 3: f1[40:] + other_next, 6: f1[40:] + same_next})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 100)], _parse)
    assert stats.stitched == 1
    assert frames[0].extra_ranges[-1][0] == 6 * CS         # the candidate WITH a same-camera continuation wins


def test_two_equally_good_continuations_are_ambiguous_and_left_alone():
    f1, f2 = _frame(0, 1, 100), _frame(0, 2, 30)
    disk = _layout({0: _first_cluster(f1), 3: f1[40:] + f2, 6: f1[40:] + f2})
    frames, stats = stitch(disk, len(disk), [PART], [], [_open_from(1, 100)], _parse)
    assert frames == [] and stats.ambiguous == 1


def test_no_partition_geometry_means_no_stitching():
    disk = _layout({})
    frames, stats = stitch(disk, len(disk), [], [], [_open_from(1, 100)], _parse)
    assert frames == [] and stats.unresolved == 1


def test_stitched_frames_are_coalesced_into_the_segments_export_ranges():
    from backend.reconstructor import label_all
    a = RawFrame(brand="dahua", camera=0, sequence=1, timestamp=T0, disk_offset=100, frame_size=50, frame_type=0xFD,
                 is_keyframe=True, extra_ranges=((400, 430), (900, 920)))
    b = RawFrame(brand="dahua", camera=0, sequence=2, timestamp=T0.replace(microsecond=100000), disk_offset=920, frame_size=30,
                 frame_type=0xFC, is_keyframe=False)
    segs = label_all([a, b], "ev")
    ranges = [(o.start, o.end) for o in segs[0].disk_offsets]
    assert ranges == [(100, 150), (400, 430), (900, 950)]              # frame b continues straight on from a's last piece


# ── on a whole generated disk (needs ffmpeg) ──────────────────────────────────

@pytest.fixture(scope="module")
def tiny_cluster_disk(tmp_path_factory):
    sys.path.insert(0, str(TOOLS))
    try:
        import make_test_pack as M
    finally:
        sys.path.remove(str(TOOLS))
    d = tmp_path_factory.mktemp("stitch")
    streams = []
    for src in ("testsrc", "smptebars"):
        out = d / f"{src}.h264"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{src}=duration=3:size=320x240:rate=10",
                        "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-g", "25", "-bf", "0",
                        "-f", "h264", str(out)], check=True)
        streams.append(out.read_bytes())
    _, wiped, _, extra = M.build_dahua(streams[0], streams[1], sectors_per_cluster=8)      # 4 KiB clusters, index wiped
    path = d / "tiny.dd"
    path.write_bytes(wiped)
    return path, extra["dahua_streams"]


def _original_frames(dhav: bytes):
    """{(channel, sequence): frame bytes} of a generated DHAV stream (skipping its 512-byte DHII sector)."""
    out, pos = {}, 512
    while pos + 24 <= len(dhav):
        assert dhav[pos:pos + 4] == b"DHAV"
        total = struct.unpack_from("<I", dhav, pos + 12)[0]
        out[(dhav[pos + 6], struct.unpack_from("<I", dhav, pos + 8)[0])] = dhav[pos:pos + total]
        pos += total
    return out


@NEED_FFMPEG
def test_tiny_clusters_are_stitched_and_every_stitched_frame_is_byte_exact(tiny_cluster_disk):
    from backend.acquisition import EvidenceImage
    from backend.plugins.dahua import DahuaPlugin
    path, (d1, d2) = tiny_cluster_disk
    originals = {**_original_frames(d1), **_original_frames(d2)}
    with EvidenceImage.open(path) as img:
        frames, note = DahuaPlugin().carve(img)
        assert "put back together" in note
        stitched = [f for f in frames if f.extra_ranges]
        assert len(stitched) > 5, note                                   # before this change every one of them was lost
        for f in frames:                                                 # nothing wrong may ever come out
            data = b"".join(img.mm[a:b] for a, b in [(f.disk_offset, f.disk_offset_end), *f.extra_ranges])
            assert data == originals[(f.camera, f.sequence)], (f.camera, f.sequence)
        found = {(f.camera, f.sequence) for f in frames}
    assert len(found) >= 0.9 * len(originals)                            # a frame whose HEADER straddles a cluster is still lost


@NEED_FFMPEG
def test_a_flat_disk_without_geometry_is_unchanged(tiny_cluster_disk, tmp_path):
    """No DHFS boot sector, no stitching: the flat CP Plus-style image carves exactly as before."""
    sys.path.insert(0, str(TOOLS))
    try:
        import make_test_pack as M
    finally:
        sys.path.remove(str(TOOLS))
    from backend.acquisition import EvidenceImage
    from backend.plugins.dahua import DahuaPlugin
    _, (d1, d2) = tiny_cluster_disk
    D = M._dhfs_module(600)
    flat = tmp_path / "flat.dd"
    flat.write_bytes(M.build_cpplus(d1, d2, D))
    with EvidenceImage.open(flat) as img:
        frames, note = DahuaPlugin().carve(img)
    assert "put back together" not in note and not any(f.extra_ranges for f in frames)


# ── frame-number gaps are reported ────────────────────────────────────────────

def _carved(seq, t):
    return RawFrame(brand="dahua", camera=0, sequence=seq, timestamp=T0.replace(second=t), disk_offset=seq * 100, frame_size=90,
                    frame_type=0xFC, is_keyframe=False)


def test_frame_number_jumps_are_reported_in_the_segment_notes():
    from backend.reconstructor import label_all
    # jumps of up to 3 stay inside one recording (a bigger one starts a new segment, as before)
    seg = label_all([_carved(s, i) for i, s in enumerate([1, 2, 3, 5, 6, 9, 10])], "ev")[0]
    assert "jump 2 time(s): about 3 frame(s) are absent" in seg.notes


def test_a_complete_run_of_frame_numbers_reports_nothing():
    from backend.reconstructor import label_all
    seg = label_all([_carved(s, s) for s in range(1, 8)], "ev")[0]
    assert "frame numbers jump" not in seg.notes


def test_index_fragments_are_not_checked_for_frame_numbers():
    from backend.reconstructor import label_all
    frags = [RawFrame(brand="dahua", camera=1, sequence=n, timestamp=T0.replace(second=n), disk_offset=n * 1000, frame_size=900,
                      frame_type=0, is_keyframe=False, stream_id=5) for n in (1, 2, 9)]
    assert "frame numbers jump" not in label_all(frags, "ev")[0].notes
