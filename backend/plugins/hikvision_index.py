"""
hikvision_index.py — Hikvision master sector and HIKBTREE data-block entries.

Source: Han, Jeong, Lee, "Analysis of the HIKVISION DVR File System", ICDF2C 2015
(LNICST 157, pp. 189-199), section 2.1 / 2.4, Figures 2, 5 and 6. Trust level L1 with
arithmetic self-consistency (docs/format_verification.md). NOT validated on a real
Hikvision disk. Field offsets were read from the paper's hex-dump figures.

Everything here is validated against the master sector's own numbers, so a misparse
is rejected rather than reported as an index entry.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.plugins.constants import (
    HIKV_BLOCK_SIZE_MAX,
    HIKV_BTREE_HDR_FOOTER,
    HIKV_BTREE_HDR_PAGE1,
    HIKV_BTREE_HDR_PAGELIST,
    HIKV_BLOCK_SIZE_MIN,
    HIKV_BTREE_MAX_BYTES,
    HIKV_BTREE_SIGNATURE,
    HIKV_ENTRY_OFF_BLOCK,
    HIKV_ENTRY_OFF_CHANNEL,
    HIKV_ENTRY_OFF_EXISTENCE,
    HIKV_ENTRY_OFF_START,
    HIKV_ENTRY_PREFIX,
    HIKV_ENTRY_SIZE,
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
    HIKV_MASTER_SECTOR_SEARCH_BYTES,
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
    HIKV_OFNI_MARKER,
    HIKV_OFNI_MIN_TIME,
    HIKV_OFNI_SIZE_OFF,
    HIKV_OFNI_TIME_OFF,
    HIKV_PAGE_ENTRIES,
    HIKV_PAGE_SIZE,
    HIKV_PAGELIST_ENTRIES,
    HIKV_TIME_SENTINEL_END,
    HIKV_TIME_SENTINEL_START,
)

_MIN_UNIX = 946684800  # 2000-01-01


@dataclass(frozen=True)
class MasterSector:
    capacity: int
    log_offset: int
    log_size: int
    video_area_offset: int
    block_size: int
    block_count: int
    btree1_offset: int
    btree1_size: int
    btree2_offset: int
    btree2_size: int
    init_time: int
    extra_offset: int = 0            # how far the file system is shifted inside the image (0x210 - 0x200 on the real disk)

    def block_offset(self, index: int) -> int:
        """Disk offset of data block `index` in THIS image (the stored pointer plus the shift)."""
        return self.video_area_offset + index * self.block_size + self.extra_offset


@dataclass(frozen=True)
class BlockEntry:
    entry_pos: int                  # position of this entry inside the HIKBTREE region
    has_video: bool                 # existence field: 00.. = video, FF.. = none/overwritten
    channel: Optional[int]          # 1-based camera number, None if the entry carries none
    start: Optional[datetime]       # UTC, None when the sentinel is present
    end: Optional[datetime]
    block_offset: int               # disk offset of the data block
    block_index: int


def parse_master_sector(data: bytes) -> Optional[MasterSector]:
    """Parse a 256-byte master sector. Returns None if the signature is absent."""
    if len(data) < HIKV_MS_SIZE or not data.startswith(HIKV_MASTER_SECTOR_MAGIC):
        return None

    def u64(off: int) -> int:
        return struct.unpack_from("<Q", data, off)[0]

    def u32(off: int) -> int:
        return struct.unpack_from("<I", data, off)[0]

    return MasterSector(
        capacity=u64(HIKV_MS_OFF_CAPACITY),
        log_offset=u64(HIKV_MS_OFF_LOG_OFFSET),
        log_size=u64(HIKV_MS_OFF_LOG_SIZE),
        video_area_offset=u64(HIKV_MS_OFF_VIDEO_AREA),
        block_size=u64(HIKV_MS_OFF_BLOCK_SIZE),
        block_count=u32(HIKV_MS_OFF_BLOCK_COUNT),
        btree1_offset=u64(HIKV_MS_OFF_BTREE1_OFFSET),
        btree1_size=u32(HIKV_MS_OFF_BTREE1_SIZE),
        btree2_offset=u64(HIKV_MS_OFF_BTREE2_OFFSET),
        btree2_size=u32(HIKV_MS_OFF_BTREE2_SIZE),
        init_time=u32(HIKV_MS_OFF_INIT_TIME),
    )


def master_sector_problems(ms: MasterSector) -> list[str]:
    """
    Arithmetic self-consistency checks derived from the paper's own sample.
    An empty list means the fields fit together like a real Hikvision disk's would.
    """
    problems: list[str] = []
    if not (HIKV_BLOCK_SIZE_MIN <= ms.block_size <= HIKV_BLOCK_SIZE_MAX):
        problems.append(f"block size {ms.block_size:#x} outside plausible range")
    if ms.block_count <= 0 or ms.block_count > 1_000_000:
        problems.append(f"block count {ms.block_count} implausible")
    if ms.block_size and ms.block_count and (
        ms.video_area_offset + ms.block_count * ms.block_size > ms.capacity
    ):
        problems.append("video data area extends past the stated capacity")
    if ms.log_offset + ms.log_size > ms.video_area_offset:
        problems.append("system logs overlap the video data area")
    if ms.btree2_offset < ms.btree1_offset + ms.btree1_size:
        problems.append("backup HIKBTREE overlaps the primary")
    if not (0 < ms.btree1_size <= HIKV_BTREE_MAX_BYTES):
        problems.append("HIKBTREE size implausible")
    return problems


def find_master_sector(mm, image_size: int) -> Optional[MasterSector]:
    """
    Locate the master sector by its signature within HIKV_MASTER_SECTOR_SEARCH_BYTES after 0x200 (Han's disk had it at
    exactly 0x200; a real disk had it at 0x210). The distance from 0x200 becomes `extra_offset`, which every pointer
    read from the disk must be shifted by.
    """
    if image_size < HIKV_MASTER_SECTOR_OFFSET + HIKV_MS_SIZE:
        return None
    end = min(image_size, HIKV_MASTER_SECTOR_OFFSET + HIKV_MASTER_SECTOR_SEARCH_BYTES + HIKV_MS_SIZE)
    window = bytes(mm[HIKV_MASTER_SECTOR_OFFSET:end])
    pos = window.find(HIKV_MASTER_SECTOR_MAGIC)
    if pos < 0:
        return None
    start = HIKV_MASTER_SECTOR_OFFSET + pos
    if start + HIKV_MS_SIZE > image_size:
        return None
    ms = parse_master_sector(bytes(mm[start : start + HIKV_MS_SIZE]))
    if ms is None:
        return None
    return MasterSector(**{**ms.__dict__, "extra_offset": pos})


def read_master_sector(mm, image_size: int) -> Optional[MasterSector]:
    """Kept for callers that expect this name; the signature may be up to 4 KiB after 0x200."""
    return find_master_sector(mm, image_size)


def _ts(value: int) -> Optional[datetime]:
    if not (_MIN_UNIX <= value <= int(time.time()) + 86400):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def parse_entry(buf: bytes, ms: MasterSector, entry_pos: int = 0, strict: bool = True) -> Optional[BlockEntry]:
    """
    Parse one 48-byte data-block entry (Fig. 6B); None if it does not fit the master sector.
    strict=True (blind scanning) also requires the 'always zero' bytes to be zero, to keep false hits rare;
    entries located structurally through the page list use strict=False.
    """
    if len(buf) < HIKV_ENTRY_SIZE:
        return None
    existence = buf[HIKV_ENTRY_OFF_EXISTENCE : HIKV_ENTRY_OFF_EXISTENCE + 8]
    if existence == b"\x00" * 8:
        has_video = True
    elif existence == b"\xff" * 8:
        has_video = False
    else:
        return None

    block_off = struct.unpack_from("<Q", buf, HIKV_ENTRY_OFF_BLOCK)[0]
    rel = block_off - ms.video_area_offset
    if rel < 0 or ms.block_size == 0 or rel % ms.block_size != 0:
        return None
    index = rel // ms.block_size
    if index >= ms.block_count:
        return None

    ch_byte = buf[HIKV_ENTRY_OFF_CHANNEL]
    if has_video:
        # bytes 0x10 and 0x12..0x17 are zero in every published sample
        if strict and (buf[0x10] != 0 or any(buf[0x12:0x18])):
            return None
        if not (1 <= ch_byte <= 128):
            return None
        channel: Optional[int] = ch_byte
    else:
        channel = None

    start_raw, end_raw = struct.unpack_from("<II", buf, HIKV_ENTRY_OFF_START)
    if (start_raw, end_raw) == (HIKV_TIME_SENTINEL_START, HIKV_TIME_SENTINEL_END):
        start = end = None
    else:
        start, end = _ts(start_raw), _ts(end_raw)
        if start is None or end is None:
            return None
        if end < start:
            # A real 1 TB disk had 7 video entries (of 852) whose end time is earlier than the start (clock change
            # or paused recording). The block and camera are still valid, the window is not: keep the entry, drop the window.
            start = end = None
    return BlockEntry(entry_pos, has_video, channel, start, end, block_off, index)


def scan_entries(mm, ms: MasterSector, image_size: int) -> list[BlockEntry]:
    """
    Find data-block entries in the HIKBTREE region. The page layout (page list and
    next-page pointers) is only partly published, so entries are located by their fixed
    48-byte structure and validated against the master sector; the paper's guarantee
    (block offset = video area + n x block size) makes false hits rare.
    Tries the primary HIKBTREE, then the backup.
    """
    for offset, size in ((ms.btree1_offset, ms.btree1_size), (ms.btree2_offset, ms.btree2_size)):
        if size <= 0 or size > HIKV_BTREE_MAX_BYTES or offset < 0 or offset + size > image_size:
            continue
        offset += ms.extra_offset
        if offset < 0 or offset + size > image_size:
            continue
        region = bytes(mm[offset : offset + size])
        if not region.startswith(HIKV_BTREE_SIGNATURE):
            continue
        entries: list[BlockEntry] = []
        pos = 0
        while pos + HIKV_ENTRY_SIZE <= len(region):
            e = parse_entry(region[pos : pos + HIKV_ENTRY_SIZE], ms, pos)
            if e is not None:
                entries.append(e)
                pos += HIKV_ENTRY_SIZE
            else:
                pos += 16
        if entries:
            return entries
    return []


def read_paged_entries(mm, ms: MasterSector, image_size: int) -> list[BlockEntry]:
    """
    Read the data-block entries the way the real disk stores them: HIKBTREE header -> page list -> 4 KiB pages,
    each page holding 48-byte entries that start with FF*8 (layout confirmed on a real 1 TB disk; see constants).
    Defensive: every offset is bounds-checked, page offsets must lie inside the HIKBTREE region, loops are
    impossible (each page is read once). Returns [] if the structure is not present, so the caller can fall back to
    the blind scan.
    """
    for base, size in ((ms.btree1_offset, ms.btree1_size), (ms.btree2_offset, ms.btree2_size)):
        if size <= 0 or size > HIKV_BTREE_MAX_BYTES:
            continue
        head_at = base + ms.extra_offset
        if head_at < 0 or head_at + 128 > image_size:
            continue
        head = bytes(mm[head_at : head_at + 128])
        if not head.startswith(HIKV_BTREE_SIGNATURE):
            continue
        pagelist_off = struct.unpack_from("<Q", head, HIKV_BTREE_HDR_PAGELIST)[0]
        if not (base <= pagelist_off < base + size):
            continue
        pl_at = pagelist_off + ms.extra_offset
        if pl_at + 8 > image_size:
            continue
        total = struct.unpack_from("<I", bytes(mm[pl_at : pl_at + 4]), 0)[0]
        if not (0 < total <= size // HIKV_PAGE_SIZE + 1):
            continue
        need = min(HIKV_PAGELIST_ENTRIES + total * HIKV_ENTRY_SIZE, size, image_size - pl_at)
        plist = bytes(mm[pl_at : pl_at + need])

        entries: list[BlockEntry] = []
        seen: set[int] = set()
        for i in range(total):
            rec_at = HIKV_PAGELIST_ENTRIES + i * HIKV_ENTRY_SIZE
            if rec_at + 8 > len(plist):
                break
            page_off = struct.unpack_from("<Q", plist, rec_at)[0]
            if page_off in seen or not (base <= page_off < base + size):
                continue
            seen.add(page_off)
            pg_at = page_off + ms.extra_offset
            if pg_at + HIKV_PAGE_SIZE > image_size:
                continue
            page = bytes(mm[pg_at : pg_at + HIKV_PAGE_SIZE])
            pos = HIKV_PAGE_ENTRIES
            while pos + HIKV_ENTRY_SIZE <= len(page) and page[pos : pos + 8] == HIKV_ENTRY_PREFIX:
                e = parse_entry(page[pos : pos + HIKV_ENTRY_SIZE], ms, page_off + pos - base, strict=False)
                if e is not None:
                    entries.append(e)
                pos += HIKV_ENTRY_SIZE
        if entries:
            return entries
    return []


def read_entries(mm, ms: MasterSector, image_size: int) -> tuple[list[BlockEntry], str]:
    """Structured page-list read first, blind 48-byte scan as the fallback. Returns (entries, method)."""
    entries = read_paged_entries(mm, ms, image_size)
    if entries:
        return entries, "HIKBTREE page list"
    return scan_entries(mm, ms, image_size), "blind 48-byte scan (page list not usable)"


def read_idr_times(mm, block_start: int, block_size: int, image_size: int) -> list[int]:
    """
    UNIX times of the IDR (key) frames listed in a data block's OFNI table (56-byte records in the last ~1 % of
    the block). Only the time field is understood; records with a wrong size or an implausible time are ignored.
    Informational: it is not used to cut or assign segments.
    """
    tail = max(block_size // 100, 100_000)
    end = min(block_start + block_size, image_size)
    start = max(block_start, end - tail)
    if end <= start:
        return []
    data = bytes(mm[start:end])
    now = int(time.time()) + 86400
    out: list[int] = []
    pos = data.find(HIKV_OFNI_MARKER)
    while pos >= 0 and len(out) < 1_000_000:
        rec = data[pos : pos + 56]
        if len(rec) == 56 and struct.unpack_from("<I", rec, HIKV_OFNI_SIZE_OFF)[0] == 56:
            t = struct.unpack_from("<I", rec, HIKV_OFNI_TIME_OFF)[0]
            if HIKV_OFNI_MIN_TIME <= t <= now:
                out.append(t)
        pos = data.find(HIKV_OFNI_MARKER, pos + 4)
    return out
