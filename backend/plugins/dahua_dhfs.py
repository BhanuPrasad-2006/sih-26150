"""
dahua_dhfs.py — Dahua DHFS 4.1 disk index (partition table, boot sector, descriptor table).

Sources: Wullen 2025 (spec + X-Tension, BSD-3) and Batista's dhfs_extractor (independent, read
only). Trust level L2 for the fields listed in constants.py; see docs/format_verification.md for
the conflicts (free-descriptor byte, fragment count) and how they are handled. NOT validated on a
real Dahua disk. Timestamps use the same packed-bitfield layout as DHAV (FFmpeg get_timeinfo).

An index recording is a chain of clusters: the main descriptor's cluster, then the descriptors
linked by `next`. The chain is authoritative; the declared fragment count is not used because the
two implementations disagree on it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.plugins.constants import (
    DHFS_BOOT_OFF_BEGIN,
    DHFS_BOOT_OFF_DESC_COUNT,
    DHFS_BOOT_OFF_DESC_TABLE,
    DHFS_BOOT_OFF_END,
    DHFS_BOOT_OFF_SECTOR_SIZE,
    DHFS_BOOT_OFF_SECTORS_PER_CLUSTER,
    DHFS_BOOT_OFF_VIDEO_AREA,
    DHFS_DESC_FRAGMENT,
    DHFS_DESC_MAIN,
    DHFS_DESC_OFF_BEGIN,
    DHFS_DESC_OFF_CHANNEL,
    DHFS_DESC_OFF_END,
    DHFS_DESC_OFF_LAST_SIZE,
    DHFS_DESC_OFF_NEXT,
    DHFS_DESC_OFF_VIDEO_ID,
    DHFS_DESC_SIZE,
    DHFS_MAX_DESCRIPTORS,
    DHFS_MAX_PARTITIONS,
    DHFS_PART_END_MAGIC,
    DHFS_PART_ENTRIES_START,
    DHFS_PART_ENTRY_SIZE,
    DHFS_PART_OFF_BOOT,
    DHFS_PART_OFF_LENGTH,
    DHFS_PART_OFF_START,
    DHFS_PART_TABLE_OFFSET,
    DHFS_SIGNATURE,
)

_END_OF_CHAIN = (0, 0xFFFFFFFF)


def decode_dhfs_time(raw: int) -> Optional[datetime]:
    """Packed local-clock time (yr6/mo4/day5/hr5/min6/sec6, +2000). None if not a valid date."""
    sec, minute, hour = raw & 0x3F, (raw >> 6) & 0x3F, (raw >> 12) & 0x1F
    day, month, year = (raw >> 17) & 0x1F, (raw >> 22) & 0x0F, ((raw >> 26) & 0x3F) + 2000
    try:
        return datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class Partition:
    number: int
    start: int              # bytes from disk start
    sector_size: int
    cluster_size: int       # bytes
    desc_table: int         # absolute byte offset of the descriptor table
    video_area: int         # absolute byte offset of cluster 0
    desc_count: int
    begin: Optional[datetime]
    end: Optional[datetime]

    def cluster_offset(self, index: int) -> int:
        return self.video_area + index * self.cluster_size


@dataclass(frozen=True)
class Fragment:
    desc_index: int
    offset: int             # absolute byte offset of the cluster
    size: int               # bytes used (the last fragment may be shorter than a cluster)
    begin: Optional[datetime]
    end: Optional[datetime]


@dataclass
class Recording:
    partition: int
    main_index: int
    camera: int             # 1-based, (channel byte & 0x0F) + 1
    begin: Optional[datetime]
    end: Optional[datetime]
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def stream_id(self) -> int:
        return (self.partition << 24) | (self.main_index + 1)


def read_partition_table(mm, size: int) -> list[tuple[int, int, int]]:
    """Return [(boot_sector_offset_sectors, partition_start_sectors, length_sectors)], or [] if not DHFS 4.1."""
    if size < DHFS_PART_TABLE_OFFSET + 512 or bytes(mm[0 : len(DHFS_SIGNATURE)]) != DHFS_SIGNATURE:
        return []
    entries: list[tuple[int, int, int]] = []
    pos = DHFS_PART_TABLE_OFFSET + DHFS_PART_ENTRIES_START
    for _ in range(DHFS_MAX_PARTITIONS):
        if pos + DHFS_PART_ENTRY_SIZE > size:
            return []
        entry = bytes(mm[pos : pos + DHFS_PART_ENTRY_SIZE])
        if entry[:4] == DHFS_PART_END_MAGIC:
            return entries
        boot = struct.unpack_from("<I", entry, DHFS_PART_OFF_BOOT)[0]
        start = struct.unpack_from("<Q", entry, DHFS_PART_OFF_START)[0]
        length = struct.unpack_from("<I", entry, DHFS_PART_OFF_LENGTH)[0]
        entries.append((boot, start, length))
        pos += DHFS_PART_ENTRY_SIZE
    return []   # no terminating magic within the allowed number of entries: not a valid table


def read_partition(mm, size: int, number: int, entry: tuple[int, int, int]) -> Optional[Partition]:
    """Parse and sanity-check one partition's boot sector."""
    boot_sectors, start_sectors, _length = entry
    # Sector size is defined in the boot sector itself; the table's units are 512-byte sectors.
    start = start_sectors * 512
    boot_at = start + boot_sectors * 512
    if boot_at + 0x150 > size:
        return None
    bs = bytes(mm[boot_at : boot_at + 0x150])
    sector_size = struct.unpack_from("<I", bs, DHFS_BOOT_OFF_SECTOR_SIZE)[0]
    spc = struct.unpack_from("<I", bs, DHFS_BOOT_OFF_SECTORS_PER_CLUSTER)[0]
    desc_off = struct.unpack_from("<I", bs, DHFS_BOOT_OFF_DESC_TABLE)[0]
    video_off = struct.unpack_from("<I", bs, DHFS_BOOT_OFF_VIDEO_AREA)[0]
    count = struct.unpack_from("<I", bs, DHFS_BOOT_OFF_DESC_COUNT)[0]
    if sector_size not in (512, 1024, 2048, 4096) or not (0 < spc <= 1 << 20) or not (0 < count <= DHFS_MAX_DESCRIPTORS):
        return None
    desc_table = start + desc_off * sector_size
    video_area = start + video_off * sector_size
    # Layout must be ordered: descriptor table inside the partition, before the video area.
    if not (desc_table < video_area) or desc_table + count * DHFS_DESC_SIZE > video_area:
        return None
    if desc_table + DHFS_DESC_SIZE > size:
        return None
    return Partition(
        number=number, start=start, sector_size=sector_size, cluster_size=spc * sector_size,
        desc_table=desc_table, video_area=video_area, desc_count=count,
        begin=decode_dhfs_time(struct.unpack_from("<I", bs, DHFS_BOOT_OFF_BEGIN)[0]),
        end=decode_dhfs_time(struct.unpack_from("<I", bs, DHFS_BOOT_OFF_END)[0]),
    )


def read_partitions(mm, size: int) -> list[Partition]:
    parts: list[Partition] = []
    for i, entry in enumerate(read_partition_table(mm, size)):
        p = read_partition(mm, size, i, entry)
        if p is not None:
            parts.append(p)
    return parts


def iter_recordings(mm, size: int, part: Partition) -> list[Recording]:
    """
    Follow each main descriptor's chain. A chain stops at the end marker, a loop, an
    out-of-range id, a non-fragment descriptor, or a fragment that names a different video.
    """
    readable = max(0, min(part.desc_count, (size - part.desc_table) // DHFS_DESC_SIZE))
    raw = bytes(mm[part.desc_table : part.desc_table + readable * DHFS_DESC_SIZE])

    def desc(i: int) -> bytes:
        return raw[i * DHFS_DESC_SIZE : (i + 1) * DHFS_DESC_SIZE]

    def u32(d: bytes, off: int) -> int:
        return struct.unpack_from("<I", d, off)[0]

    recordings: list[Recording] = []
    for idx in range(readable):
        d = desc(idx)
        if d[0] != DHFS_DESC_MAIN:
            continue
        begin, end = decode_dhfs_time(u32(d, DHFS_DESC_OFF_BEGIN)), decode_dhfs_time(u32(d, DHFS_DESC_OFF_END))
        if begin is None or end is None or u32(d, DHFS_DESC_OFF_BEGIN) == u32(d, DHFS_DESC_OFF_END):
            continue        # an unused/empty main descriptor (Batista skips begin == end too)
        camera = (d[DHFS_DESC_OFF_CHANNEL] & 0x0F) + 1
        last_sectors = u32(d, DHFS_DESC_OFF_LAST_SIZE)
        rec = Recording(part.number, idx, camera, begin, end)

        chain = [idx]
        seen = {idx}
        cur = u32(d, DHFS_DESC_OFF_NEXT)
        while cur not in _END_OF_CHAIN and cur < readable and cur not in seen:
            fd = desc(cur)
            if fd[0] != DHFS_DESC_FRAGMENT or u32(fd, DHFS_DESC_OFF_VIDEO_ID) != idx:
                break
            chain.append(cur)
            seen.add(cur)
            cur = u32(fd, DHFS_DESC_OFF_NEXT)

        for pos_in_chain, di in enumerate(chain):
            dd = desc(di)
            is_last = pos_in_chain == len(chain) - 1
            nbytes = part.cluster_size
            if is_last and 0 < last_sectors * part.sector_size <= part.cluster_size:
                nbytes = last_sectors * part.sector_size
            off = part.cluster_offset(di)
            if off + 1 > size:
                break
            rec.fragments.append(Fragment(
                desc_index=di, offset=off, size=min(nbytes, size - off),
                begin=decode_dhfs_time(u32(dd, DHFS_DESC_OFF_BEGIN)),
                end=decode_dhfs_time(u32(dd, DHFS_DESC_OFF_END)),
            ))
        if rec.fragments:
            recordings.append(rec)
    return recordings
