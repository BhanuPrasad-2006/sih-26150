"""
Hikvision index tests built from values printed by a THIRD-PARTY tool run on a REAL 1 TB Hikvision disk.

Source of the values: the published output (analysis/*.json) of github.com/vishwajitsarnobat/HIKVISION-DVR-Tool, produced
from an E01 image of a real DVR disk ("dvr_test_img.E01", 1,000,204,886,016 bytes). That repository has no licence, so
no code or data files were copied: only the numeric facts below are used, each cited. We have NOT seen the disk image;
these tests check that our parser agrees with an independent parser's readings of it, and they encode what the real
disk taught us: the file system was shifted by 16 bytes (signature at 0x210, not 0x200), the index is stored in 4 KiB
pages, and 7 of 852 video entries have an end time earlier than the start.
"""

import shutil
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.plugins.constants import (
    HIKV_ENTRY_SIZE, HIKV_MASTER_SECTOR_MAGIC, HIKV_MS_OFF_BLOCK_COUNT, HIKV_MS_OFF_BLOCK_SIZE, HIKV_MS_OFF_BTREE1_OFFSET,
    HIKV_MS_OFF_BTREE1_SIZE, HIKV_MS_OFF_BTREE2_OFFSET, HIKV_MS_OFF_BTREE2_SIZE, HIKV_MS_OFF_CAPACITY,
    HIKV_MS_OFF_INIT_TIME, HIKV_MS_OFF_LOG_OFFSET, HIKV_MS_OFF_LOG_SIZE, HIKV_MS_OFF_VIDEO_AREA, HIKV_MS_SIZE,
)
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.hikvision_index import (
    find_master_sector, master_sector_problems, parse_entry, parse_master_sector, read_entries, read_idr_times,
    read_paged_entries, scan_entries,
)

# ── Master sector of the real 1 TB disk (raw bytes and values printed by the third-party tool) ───────────────
REAL_SIG_AT = 0x210
REAL = dict(
    capacity=0xE8E0DB6000, log_offset=0x3D13200, log_size=0xF42C00, video_area=0x4C5E000, block_size=0x40000000,
    block_count=0x3A3, btree1=0xE8E0D4DC00, btree1_size=0x1A000, btree2=0xE8E0D67C00, btree2_size=0x1A000,
    init_time=1646919412,                       # 2022-03-10 19:06:52 UTC
)


def _ms_bytes(v: dict) -> bytes:
    b = bytearray(HIKV_MS_SIZE)
    b[: len(HIKV_MASTER_SECTOR_MAGIC)] = HIKV_MASTER_SECTOR_MAGIC
    struct.pack_into("<Q", b, HIKV_MS_OFF_CAPACITY, v["capacity"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_LOG_OFFSET, v["log_offset"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_LOG_SIZE, v["log_size"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_VIDEO_AREA, v["video_area"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_BLOCK_SIZE, v["block_size"])
    struct.pack_into("<I", b, HIKV_MS_OFF_BLOCK_COUNT, v["block_count"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_BTREE1_OFFSET, v["btree1"])
    struct.pack_into("<I", b, HIKV_MS_OFF_BTREE1_SIZE, v["btree1_size"])
    struct.pack_into("<Q", b, HIKV_MS_OFF_BTREE2_OFFSET, v["btree2"])
    struct.pack_into("<I", b, HIKV_MS_OFF_BTREE2_SIZE, v["btree2_size"])
    struct.pack_into("<I", b, HIKV_MS_OFF_INIT_TIME, v["init_time"])
    return bytes(b)


class _Mem:
    def __init__(self, b): self.b = b
    def __getitem__(self, k): return self.b[k]
    def __len__(self): return len(self.b)


def test_real_master_sector_values_parse_and_are_arithmetically_consistent():
    ms = parse_master_sector(_ms_bytes(REAL))
    assert (ms.capacity, ms.block_size, ms.block_count) == (1000204886016, 1 << 30, 931)
    assert ms.video_area_offset == 80076800 and ms.log_offset == 64041472 and ms.log_size == 16002048
    assert ms.btree1_offset == 1000204459008 and ms.btree2_offset == 1000204565504
    assert ms.btree1_offset + ms.btree1_size == ms.btree2_offset                  # primary ends where the backup starts
    assert master_sector_problems(ms) == []                                       # our self-consistency checks accept it
    assert ms.video_area_offset + ms.block_count * ms.block_size <= ms.capacity
    # The third-party tool printed "2022-03-10 19:06:52 UTC" for this value, but 1646919412 is 13:36:52 UTC: its
    # "UTC" labels are its author's local time (IST). Only the raw epoch value is trusted here.
    assert datetime.fromtimestamp(ms.init_time, tz=timezone.utc).isoformat().startswith("2022-03-10T13:36:52")


def test_signature_is_found_at_0x210_and_pointers_are_shifted():
    img = bytearray(0x1000)
    img[REAL_SIG_AT : REAL_SIG_AT + HIKV_MS_SIZE] = _ms_bytes(REAL)
    ms = find_master_sector(_Mem(bytes(img)), 10 ** 13)
    assert ms is not None and ms.extra_offset == 0x10
    assert ms.block_offset(0) == REAL["video_area"] + 0x10
    assert ms.block_offset(930) == REAL["video_area"] + 930 * (1 << 30) + 0x10


def test_signature_at_han_position_means_no_shift_and_far_signature_is_ignored():
    img = bytearray(0x3000)
    img[0x200 : 0x200 + HIKV_MS_SIZE] = _ms_bytes(REAL)
    assert find_master_sector(_Mem(bytes(img)), 10 ** 13).extra_offset == 0
    far = bytearray(0x4000)
    far[0x2000 : 0x2000 + HIKV_MS_SIZE] = _ms_bytes(REAL)                         # more than 4 KiB after 0x200
    assert find_master_sector(_Mem(bytes(far)), 10 ** 13) is None


# ── Real entries (values printed for the disk) ───────────────────────────────

def _entry(channel, start, end, block_offset, has_video=True):
    b = bytearray(HIKV_ENTRY_SIZE)
    b[0:8] = b"\xff" * 8
    b[8:16] = (b"\x00" if has_video else b"\xff") * 8
    b[0x11] = channel
    if not has_video:
        b[0x10:0x18] = b"\xff" * 8
    struct.pack_into("<II", b, 0x18, start, end)
    struct.pack_into("<Q", b, 0x20, block_offset)
    return bytes(b)


_MS = parse_master_sector(_ms_bytes(REAL))

# (channel, start, end, block offset, has_video); block index = (offset - video area) / 1 GiB, computed below
_RAW_ENTRIES = [
    (1, 1654193835, 1654226314, 0xFC4C5E000, True),          # first entry of the index
    (1, 1654226314, 1654250506, 0x1144C5E000, True),         # starts exactly when the previous one ended
    (1, 1654250506, 1654269955, 0x1344C5E000, True),
    (2, 2147483647, 0, 0xA3C4C5E000, True),                  # video, but the time fields hold the "not set" sentinel
    (3, 2147483647, 0, 0xA444C5E000, True),
    (4, 2147483647, 0, 0xA584C5E000, True),
    (255, 2147483647, 0, 0xA844C5E000, False),               # "no video": channel 255, sentinel times
    (255, 1753111963, 1753111963, 0x384C5E000, False),       # "no video" with equal start and end
]
REAL_ENTRIES = [(*r, (r[3] - REAL["video_area"]) // REAL["block_size"]) for r in _RAW_ENTRIES]


@pytest.mark.parametrize("ch,start,end,blk,vid,idx", REAL_ENTRIES)
def test_real_entries_parse_as_the_independent_tool_read_them(ch, start, end, blk, vid, idx):
    e = parse_entry(_entry(ch, start, end, blk, vid), _MS)
    assert e is not None
    assert e.has_video is vid and e.block_index == idx and e.block_offset == blk
    assert e.channel == (ch if vid else None)                                      # 255 on a no-video entry means "none"
    if start == 2147483647:
        assert e.start is None and e.end is None                                   # the sentinel, not a date in 2038
    else:
        assert e.start == datetime.fromtimestamp(start, tz=timezone.utc) and e.end == datetime.fromtimestamp(end, tz=timezone.utc)


def test_every_real_entry_offset_is_the_video_area_plus_whole_blocks():
    assert [r[5] for r in REAL_ENTRIES][:2] == [63, 69]                            # worked by hand: 0xFC0000000 / 1 GiB = 63
    for ch, start, end, blk, vid, idx in REAL_ENTRIES:
        assert (blk - REAL["video_area"]) == idx * REAL["block_size"]              # whole blocks, no remainder
        assert 0 <= idx < REAL["block_count"]


def test_video_entry_with_end_before_start_is_kept_but_has_no_window():
    """7 of 852 video entries on the real disk look like this; the block and camera are still usable."""
    e = parse_entry(_entry(1, 1654226314, 1654193835, 0xFC4C5E000), _MS)
    assert e is not None and e.has_video and e.channel == 1 and e.block_index == 63
    assert e.start is None and e.end is None


# ── The page-structured HIKBTREE and the shifted file system, on a small image ──────────────

_BLOCK = 1024 * 1024
_SHIFT = 0x10


def _build_real_layout(entries_per_page, shift=_SHIFT, video=None, wreck_header=False):
    """
    A miniature of the real layout: signature at 0x200+shift, every pointer shifted, HIKBTREE = header + page list +
    4 KiB pages whose entries start at +80 and begin with FF*8.
    """
    video_area = 0x100000
    btree1, btree2, bsize = 0x10000, 0x20000, 0x8000
    n_blocks = 6
    total = video_area + n_blocks * _BLOCK + 0x10000
    img = bytearray(total)
    v = dict(capacity=total - shift, log_offset=0x1000, log_size=0x1000, video_area=video_area, block_size=_BLOCK,
             block_count=n_blocks, btree1=btree1, btree1_size=bsize, btree2=btree2, btree2_size=bsize, init_time=1646919412)
    img[0x200 + shift : 0x200 + shift + HIKV_MS_SIZE] = _ms_bytes(v)

    def at(nominal): return nominal + shift
    for base in (btree1, btree2):
        h = at(base)
        img[h : h + 8] = b"HIKBTREE"
        page_list = base + 0x1000
        struct.pack_into("<Q", img, h + 48, base + 0x6000)                   # footer
        struct.pack_into("<Q", img, h + 64, 0 if wreck_header else page_list)
        struct.pack_into("<Q", img, h + 72, base + 0x2000)
        pl = at(page_list)
        struct.pack_into("<I", img, pl, len(entries_per_page))
        for i, entries in enumerate(entries_per_page):
            page_off = base + 0x2000 + i * 0x1000
            struct.pack_into("<Q", img, pl + 80 + i * 48, page_off)
            pg = at(page_off)
            struct.pack_into("<Q", img, pg + 16, 0xFFFFFFFFFFFFFFFF if i == len(entries_per_page) - 1 else page_off + 0x1000)
            for j, e in enumerate(entries):
                img[pg + 80 + j * 48 : pg + 80 + (j + 1) * 48] = e
    for idx, payload in (video or {}).items():
        start = at(video_area + idx * _BLOCK) + 4096
        img[start : start + len(payload)] = payload
    return bytes(img), video_area


def _e(block_index, channel, start, end, video_area=0x100000, has_video=True):
    return _entry(channel, start, end, video_area + block_index * _BLOCK, has_video)


def test_paged_index_is_read_through_header_and_page_list():
    pages = [[_e(0, 1, 1654193835, 1654226314), _e(1, 1, 1654226314, 1654250506)],
             [_e(2, 2, 2147483647, 0), _e(3, 255, 2147483647, 0, has_video=False)]]
    img, _ = _build_real_layout(pages)
    ms = find_master_sector(_Mem(img), len(img))
    assert ms.extra_offset == _SHIFT
    entries, method = read_entries(_Mem(img), ms, len(img))
    assert method == "HIKBTREE page list"
    assert [(e.block_index, e.channel, e.has_video) for e in entries] == [(0, 1, True), (1, 1, True), (2, 2, True), (3, None, False)]
    assert entries[2].start is None                                                # sentinel kept as "no window"


def test_damaged_page_list_falls_back_to_the_blind_scan():
    pages = [[_e(0, 1, 1654193835, 1654226314), _e(1, 1, 1654226314, 1654250506)]]
    img, _ = _build_real_layout(pages, wreck_header=True)
    ms = find_master_sector(_Mem(img), len(img))
    assert read_paged_entries(_Mem(img), ms, len(img)) == []
    entries, method = read_entries(_Mem(img), ms, len(img))
    assert "blind" in method and {e.block_index for e in entries} == {0, 1}


def test_an_image_without_any_shift_still_works():
    pages = [[_e(0, 1, 1654193835, 1654226314)]]
    img, _ = _build_real_layout(pages, shift=0)
    ms = find_master_sector(_Mem(img), len(img))
    assert ms.extra_offset == 0 and read_entries(_Mem(img), ms, len(img))[1] == "HIKBTREE page list"


def test_page_offsets_pointing_outside_the_index_are_ignored():
    pages = [[_e(0, 1, 1654193835, 1654226314)]]
    img, _ = _build_real_layout(pages)
    b = bytearray(img)
    for base in (0x10000, 0x20000):                                                # primary and backup index
        struct.pack_into("<Q", b, base + 0x1000 + _SHIFT + 80, 0x7000_0000)        # page 1 points far outside
    ms = find_master_sector(_Mem(bytes(b)), len(b))
    assert read_paged_entries(_Mem(bytes(b)), ms, len(b)) == []


# ── OFNI (IDR table) times ────────────────────────────────────────────────────

def _ofni(t, size=56):
    r = bytearray(56)
    r[0:4] = b"OFNI"
    struct.pack_into("<I", r, 4, size)
    struct.pack_into("<I", r, 24, t)
    return bytes(r)


def test_idr_table_times_are_read_from_the_end_of_the_block():
    block = bytearray(_BLOCK)
    tail = b"".join([_ofni(1654200000), _ofni(1654200002), _ofni(1654200004, size=40),     # wrong size: ignored
                     _ofni(5), _ofni(1654200006)])                                      # implausible time: ignored
    block[_BLOCK - 2000 : _BLOCK - 2000 + len(tail)] = tail
    times = read_idr_times(_Mem(bytes(block)), 0, _BLOCK, _BLOCK)
    assert times == [1654200000, 1654200002, 1654200006]
    assert read_idr_times(_Mem(bytes(block[:100])), 0, _BLOCK, 100) == []


# ── End to end on a shifted image with real video ────────────────────────────

pytestmark_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg needed")


@pytestmark_ffmpeg
def test_plugin_detects_and_carves_a_shifted_image(tmp_path):
    from backend.acquisition import EvidenceImage
    from backend.tests.test_hikvision_index import _encode
    h264 = _encode("testsrc", str(tmp_path / "a.h264"))
    ofni_tail = b"".join(_ofni(1654200000 + i) for i in range(3))
    pages = [[_e(0, 1, 1654200000, 1654200003)]]
    img_bytes, video_area = _build_real_layout(pages, video={0: h264})
    b = bytearray(img_bytes)
    tail_at = (video_area + 0 * _BLOCK) + _SHIFT + _BLOCK - 3000
    b[tail_at : tail_at + len(ofni_tail)] = ofni_tail
    p = tmp_path / "hik_shifted.dd"
    p.write_bytes(bytes(b))

    with EvidenceImage.open(p) as img:
        plugin = HikvisionPlugin()
        assert plugin.detect(img) == 1.0                                              # the old code required 0x200 exactly
        frames, note = plugin.carve(img)
    assert frames, note
    assert {f.camera for f in frames} == {1}                                          # camera came from the page entry
    assert "shifted by 16 bytes" in note and "HIKBTREE page list" in note and "IDR tables" in note
    assert all(f.window_start is not None for f in frames)
