"""
test_hikvision_index.py — Hikvision master sector + HIKBTREE entries (Han, Jeong, Lee 2015).

The known-answer tests use the values PRINTED IN THE PAPER (Fig. 2 master sector, Fig. 6 data
block entries). They check that our field offsets reproduce the paper's own numbers and that
those numbers satisfy the arithmetic relationships a real disk must satisfy.
"""

import os
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.models import SegmentStatus
from backend.plugins.constants import (
    HIKV_ENTRY_SIZE,
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
    HIKV_MS_OFF_BLOCK_COUNT,
    HIKV_MS_OFF_BLOCK_SIZE,
    HIKV_MS_OFF_BTREE1_OFFSET,
    HIKV_MS_OFF_BTREE1_SIZE,
    HIKV_MS_OFF_BTREE2_OFFSET,
    HIKV_MS_OFF_BTREE2_SIZE,
    HIKV_MS_OFF_CAPACITY,
    HIKV_MS_OFF_INIT_TIME,
    HIKV_MS_OFF_LOG_OFFSET,
    HIKV_MS_OFF_LOG_SIZE,
    HIKV_MS_OFF_VIDEO_AREA,
    HIKV_MS_SIZE,
)
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.hikvision_index import (
    master_sector_problems,
    parse_entry,
    parse_master_sector,
    scan_entries,
)
from backend.reconstructor import label_all

_NEED_FFMPEG = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)

# ── Values printed in Han 2015 Fig. 2 (master sector of a 160 GB DVR disk) ────
HAN_CAPACITY = 0x25433D6000
HAN_LOG_OFFSET = 0x3D13200
HAN_LOG_SIZE = 0xF42C00
HAN_VIDEO_AREA = 0x4C5E000
HAN_BLOCK_SIZE = 0x40000000          # bytes "00 00 00 40" in Fig. 2 (text says 0x400000; see format_verification.md)
HAN_BLOCK_COUNT = 0x94
HAN_BTREE1 = 0x25433BDC00
HAN_BTREE2 = 0x25433C3C00
HAN_BTREE_SIZE = 0x6000
HAN_INIT_TIME_BYTES = bytes.fromhex("37227754")   # printed left-to-right in Fig. 2


def _han_master_sector() -> bytes:
    ms = bytearray(HIKV_MS_SIZE)
    ms[: len(HIKV_MASTER_SECTOR_MAGIC)] = HIKV_MASTER_SECTOR_MAGIC
    struct.pack_into("<Q", ms, HIKV_MS_OFF_CAPACITY, HAN_CAPACITY)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_LOG_OFFSET, HAN_LOG_OFFSET)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_LOG_SIZE, HAN_LOG_SIZE)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_VIDEO_AREA, HAN_VIDEO_AREA)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BLOCK_SIZE, HAN_BLOCK_SIZE)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BLOCK_COUNT, HAN_BLOCK_COUNT)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BTREE1_OFFSET, HAN_BTREE1)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BTREE1_SIZE, HAN_BTREE_SIZE)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BTREE2_OFFSET, HAN_BTREE2)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BTREE2_SIZE, HAN_BTREE_SIZE)
    ms[HIKV_MS_OFF_INIT_TIME : HIKV_MS_OFF_INIT_TIME + 4] = HAN_INIT_TIME_BYTES
    return bytes(ms)


def test_han_master_sector_sample_parses_to_the_papers_values():
    ms = parse_master_sector(_han_master_sector())
    assert ms is not None
    assert ms.capacity == 0x25433D6000
    assert ms.log_offset == 0x3D13200 and ms.log_size == 0xF42C00
    assert ms.video_area_offset == 0x4C5E000
    assert ms.block_count == 0x94
    assert ms.btree1_offset == 0x25433BDC00 and ms.btree1_size == 0x6000
    assert ms.btree2_offset == 0x25433C3C00 and ms.btree2_size == 0x6000
    # The paper prints the init time bytes as 37 22 77 54; read little-endian that is
    # 0x54772237 = 2014-11-30 UTC, which fits a paper written in 2015.
    assert ms.init_time == 0x54772237
    assert datetime.fromtimestamp(ms.init_time, tz=timezone.utc).year == 2014


def test_han_sample_satisfies_the_papers_own_arithmetic():
    ms = parse_master_sector(_han_master_sector())
    assert master_sector_problems(ms) == []
    # 160 GB disk / 1 GB blocks = 148 = 0x94: the printed block count and the printed capacity agree.
    assert ms.block_count == (ms.capacity - ms.video_area_offset) // ms.block_size
    # Primary HIKBTREE ends exactly where the backup begins.
    assert ms.btree1_offset + ms.btree1_size == ms.btree2_offset


def test_fields_read_at_wrong_offsets_are_rejected_by_the_arithmetic():
    """If the offsets were misread, the self-consistency check must not pass."""
    good = bytearray(_han_master_sector())
    shifted = bytearray(good[:HIKV_MS_OFF_CAPACITY]) + b"\x00" * 8 + good[HIKV_MS_OFF_CAPACITY : HIKV_MS_SIZE - 8]
    ms = parse_master_sector(bytes(shifted))
    assert ms is not None and master_sector_problems(ms) != []


# ── Fig. 6 data block entries ─────────────────────────────────────────────────

def _fig6_entries():
    ff, z = b"\xff", b"\x00"
    e1 = ff * 8 + z * 8 + z + b"\x01" + z * 6 + bytes.fromhex("7E237754" "37747754") \
        + bytes.fromhex("00E0C5C400000000") + bytes.fromhex("1000000000000000")
    e2 = ff * 8 + z * 8 + z + b"\x02" + z * 6 + bytes.fromhex("FFFFFF7F" "00000000") \
        + bytes.fromhex("00E0C5C401000000") + bytes.fromhex("2000000002000000")
    e3 = ff * 16 + ff * 11 + b"\x7f" + z * 4 \
        + bytes.fromhex("00E0C5C402000000") + bytes.fromhex("2000000000000000")
    assert len(e1) == len(e2) == len(e3) == HIKV_ENTRY_SIZE
    return e1, e2, e3


def test_han_fig6_entries_parse_to_the_documented_meanings():
    ms = parse_master_sector(_han_master_sector())
    e1, e2, e3 = (parse_entry(b, ms) for b in _fig6_entries())

    assert e1 is not None and e1.has_video and e1.channel == 1
    assert e1.start == datetime.fromtimestamp(0x5477237E, tz=timezone.utc)
    assert e1.end == datetime.fromtimestamp(0x54777437, tz=timezone.utc)
    assert e1.block_offset == 0xC4C5E000 and e1.block_index == 3    # = video area + 3 x 1 GB

    assert e2 is not None and e2.has_video and e2.channel == 2
    assert e2.start is None and e2.end is None                       # FF FF FF 7F 00 00 00 00 sentinel
    assert e2.block_index == 7                                       # 0x1C4C5E000 = area + 7 GB

    assert e3 is not None and not e3.has_video and e3.channel is None
    assert e3.block_index == 11                                      # 0x2C4C5E000 = area + 11 GB


def test_entry_pointing_outside_the_video_area_is_rejected():
    ms = parse_master_sector(_han_master_sector())
    e1 = bytearray(_fig6_entries()[0])
    struct.pack_into("<Q", e1, 0x20, HAN_VIDEO_AREA + 5)             # not a multiple of the block size
    assert parse_entry(bytes(e1), ms) is None
    struct.pack_into("<Q", e1, 0x20, HAN_VIDEO_AREA + 200 * HAN_BLOCK_SIZE)   # beyond the block count
    assert parse_entry(bytes(e1), ms) is None


# ── Synthetic indexed disk (small blocks so it fits in memory) ────────────────

_BLOCK = 1024 * 1024
_BTREE1, _BTREE2, _BTREE_SIZE = 0x3000, 0x5000, 0x2000
_VIDEO_AREA = 0x100000


def _entry(block_index: int, channel, start, end, has_video=True) -> bytes:
    b = bytearray(HIKV_ENTRY_SIZE)
    b[0:8] = b"\xff" * 8
    b[8:16] = (b"\x00" if has_video else b"\xff") * 8
    if has_video:
        b[0x11] = channel
    else:
        b[0x10:0x18] = b"\xff" * 8
    if start is None:
        struct.pack_into("<II", b, 0x18, 0x7FFFFFFF, 0)
    else:
        struct.pack_into("<II", b, 0x18, start, end)
    struct.pack_into("<Q", b, 0x20, _VIDEO_AREA + block_index * _BLOCK)
    return bytes(b)


def _build_indexed_image(blocks: dict[int, bytes], entries: list[bytes], block_count: int = 4, capacity=None) -> bytes:
    total = _VIDEO_AREA + block_count * _BLOCK
    img = bytearray(total)
    ms = bytearray(HIKV_MS_SIZE)
    ms[: len(HIKV_MASTER_SECTOR_MAGIC)] = HIKV_MASTER_SECTOR_MAGIC
    struct.pack_into("<Q", ms, HIKV_MS_OFF_CAPACITY, capacity or total)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_LOG_OFFSET, 0x1000)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_LOG_SIZE, 0x1000)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_VIDEO_AREA, _VIDEO_AREA)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BLOCK_SIZE, _BLOCK)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BLOCK_COUNT, block_count)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BTREE1_OFFSET, _BTREE1)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BTREE1_SIZE, _BTREE_SIZE)
    struct.pack_into("<Q", ms, HIKV_MS_OFF_BTREE2_OFFSET, _BTREE2)
    struct.pack_into("<I", ms, HIKV_MS_OFF_BTREE2_SIZE, _BTREE_SIZE)
    img[HIKV_MASTER_SECTOR_OFFSET : HIKV_MASTER_SECTOR_OFFSET + HIKV_MS_SIZE] = ms
    for base in (_BTREE1, _BTREE2):
        img[base : base + 8] = b"HIKBTREE"
        pos = base + 0x100
        for e in entries:
            img[pos : pos + HIKV_ENTRY_SIZE] = e
            pos += HIKV_ENTRY_SIZE
    for idx, payload in blocks.items():
        start = _VIDEO_AREA + idx * _BLOCK
        img[start + 4096 : start + 4096 + len(payload)] = payload
    return bytes(img)


def _encode(source: str, path: str) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", path],
        check=True,
    )
    return Path(path).read_bytes()


@pytest.fixture(scope="module")
def streams(tmp_path_factory):
    d = tmp_path_factory.mktemp("hik_idx")
    return _encode("testsrc", str(d / "a.h264")), _encode("smptebars", str(d / "b.h264")), _encode("testsrc2", str(d / "c.h264"))


_T1 = int(datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
_T2 = _T1 + 3600


@_NEED_FFMPEG
def test_indexed_carving_assigns_camera_and_window_and_keeps_deleted_footage(temp_dir, streams):
    a, b, c = streams
    entries = [
        _entry(0, 1, _T1, _T1 + 3599),
        _entry(1, 2, _T2, _T2 + 3599),
        _entry(2, None, None, None, has_video=False),   # overwritten/deleted: entry says no video
    ]
    path = os.path.join(temp_dir, "hik_indexed.dd")
    Path(path).write_bytes(_build_indexed_image({0: a, 1: b, 2: c}, entries))

    with EvidenceImage.open(path) as img:
        plugin = HikvisionPlugin()
        assert plugin.detect(img) == 1.0
        frames, note = plugin.carve(img)
        segs = sorted(label_all(frames, "ev"), key=lambda s: (s.camera == 0, s.camera))
        assert len(segs) == 3, note

        cam1, cam2, unindexed = segs
        assert (cam1.camera, cam2.camera, unindexed.camera) == (1, 2, 0)
        assert cam1.start_time == datetime.fromtimestamp(_T1, tz=timezone.utc)
        assert cam1.end_time == datetime.fromtimestamp(_T1 + 3599, tz=timezone.utc)
        assert cam2.start_time == datetime.fromtimestamp(_T2, tz=timezone.utc)
        assert unindexed.start_time is None                       # no window for unindexed footage
        assert "block-level window" in cam1.notes
        assert "2 block(s) had no usable entry" in note

        recovered = {s.camera: b"".join(bytes(img.mm[o.start:o.end]) for o in s.disk_offsets) for s in segs}
        assert recovered[1] == a and recovered[2] == b and recovered[0] == c   # byte-exact per block

        seg, detail = export_segment(img.mm, cam1, Path(temp_dir) / "out")
        assert "error" not in detail and detail["ffprobe_valid"] is True
        assert seg.status == SegmentStatus.PARTIAL


@_NEED_FFMPEG
def test_wiped_index_still_recovers_footage_from_the_video_area(temp_dir, streams):
    """After a system initialisation the HIKBTREE is reset but the video remains (Han 2015 3.2)."""
    a, b, _ = streams
    path = os.path.join(temp_dir, "hik_wiped.dd")
    Path(path).write_bytes(_build_indexed_image({0: a, 3: b}, entries=[]))
    with EvidenceImage.open(path) as img:
        frames, note = HikvisionPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 2 and all(s.camera == 0 and s.start_time is None for s in segs)
        assert "0 HIKBTREE data-block entries" in note
        assert "4 block(s) had no usable entry" in note


@_NEED_FFMPEG
def test_two_entries_for_one_block_are_not_assigned(temp_dir, streams):
    a, _, _ = streams
    entries = [_entry(0, 1, _T1, _T1 + 100), _entry(0, 2, _T2, _T2 + 100)]
    path = os.path.join(temp_dir, "hik_ambiguous.dd")
    Path(path).write_bytes(_build_indexed_image({0: a}, entries))
    with EvidenceImage.open(path) as img:
        frames, note = HikvisionPlugin().carve(img)
        seg = label_all(frames, "ev")[0]
        assert seg.camera == 0 and seg.start_time is None
        assert "1 block(s) had several entries" in note


@_NEED_FFMPEG
def test_inconsistent_master_sector_falls_back_to_whole_image_carving(temp_dir, streams):
    a, _, _ = streams
    # Stated capacity smaller than the video area: fails the arithmetic checks.
    raw = _build_indexed_image({0: a}, [_entry(0, 1, _T1, _T1 + 10)], capacity=0x10000)
    path = os.path.join(temp_dir, "hik_bad_ms.dd")
    Path(path).write_bytes(raw)
    with EvidenceImage.open(path) as img:
        frames, note = HikvisionPlugin().carve(img)
        assert "Master sector not usable" in note
        segs = label_all(frames, "ev")
        assert len(segs) == 1 and segs[0].camera == 0


def test_scan_entries_finds_nothing_in_garbage(temp_dir):
    ms = parse_master_sector(_han_master_sector())
    data = b"HIKBTREE" + os.urandom(HAN_BTREE_SIZE)

    class _M:
        """Sparse fake image: only the HIKBTREE region has content (the real offset is ~160 GB)."""
        def __getitem__(self, k):
            assert k.start >= HAN_BTREE1
            return data[k.start - HAN_BTREE1 : k.stop - HAN_BTREE1]

    assert scan_entries(_M(), ms, HAN_BTREE1 + len(data)) == []
