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
    HIKV_BLOCK_SIZE_MIN,
    HIKV_BTREE_MAX_BYTES,
    HIKV_BTREE_SIGNATURE,
    HIKV_ENTRY_OFF_BLOCK,
    HIKV_ENTRY_OFF_CHANNEL,
    HIKV_ENTRY_OFF_EXISTENCE,
    HIKV_ENTRY_OFF_START,
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

    def block_offset(self, index: int) -> int:
        return self.video_area_offset + index * self.block_size


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


def read_master_sector(mm, image_size: int) -> Optional[MasterSector]:
    if image_size < HIKV_MASTER_SECTOR_OFFSET + HIKV_MS_SIZE:
        return None
    return parse_master_sector(bytes(mm[HIKV_MASTER_SECTOR_OFFSET : HIKV_MASTER_SECTOR_OFFSET + HIKV_MS_SIZE]))


def _ts(value: int) -> Optional[datetime]:
    if not (_MIN_UNIX <= value <= int(time.time()) + 86400):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def parse_entry(buf: bytes, ms: MasterSector, entry_pos: int = 0) -> Optional[BlockEntry]:
    """Parse one 48-byte data-block entry (Fig. 6B); None if it does not fit the master sector."""
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
        if buf[0x10] != 0 or any(buf[0x12:0x18]):
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
        if start is None or end is None or end < start:
            return None
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
