"""
hikvision.py — Hikvision DVR/NVR brand plugin.

What is implemented in v1:
  - detect():          Look for b'HIKVISION@HANGZHOU' in a 4 KiB window after 0x200 (Han's disk: 0x200;
                       a real disk: 0x210, i.e. the whole file system shifted by 16 bytes, which is then
                       added to every pointer). Returns 1.0 on match, 0.0 otherwise.
  - list_recordings(): returns [] — index data is used inside carve() (see below).
  - carve():           Uses the master sector and HIKBTREE data-block entries from
                       Han 2015 (hikvision_index.py) to find the video blocks and, where
                       the entries survive, each block's camera and time window; inside
                       blocks it uses standards-based stream carving (MPEG-PS / H.264
                       Annex B, stream_carver.py). Falls back to whole-image carving if
                       the master sector is missing or fails its self-consistency checks.
                       Per-frame timestamps are unavailable (the OFNI IDR-table layout is
                       unpublished). Every result is UNCERTAIN until ffprobe decodes the
                       export (then PARTIAL, never COMPLETE). Not validated on a real disk.

See docs/format_verification.md and docs/format_sheets/hikvision.md.

Sources:
  [Han2015]   Han, Jeong, Lee (2015). ICDF2C, Springer (read in full).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
)
from backend.plugins.hikvision_index import (
    find_master_sector,
    master_sector_problems,
    read_entries,
    read_idr_times,
)
from backend.plugins.stream_carver import CarveRegion, carve_standard_streams

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

# Minimum bytes needed to even check the master sector
_MASTER_SECTOR_MIN_SIZE = HIKV_MASTER_SECTOR_OFFSET + len(HIKV_MASTER_SECTOR_MAGIC) + 8


class HikvisionPlugin(BrandPlugin):
    name = "hikvision"
    display_name = "Hikvision"

    def __init__(self) -> None:
        self._master_sector_found = False

    # ── detect ────────────────────────────────────────────────────────────────

    def detect(self, img: "EvidenceImage") -> float:
        """
        Read up to 1024 bytes from offset 0x200 and look for HIKVISION@HANGZHOU.

        Verified: Han 2015, cited in MDPI 2025.
        Returns 1.0 on match, 0.0 otherwise.
        """
        try:
            if img.size < _MASTER_SECTOR_MIN_SIZE:
                return 0.0

            # The signature was at 0x200 in Han's disk but at 0x210 on a real one: search a window after 0x200.
            if find_master_sector(img.mm, img.size) is not None:
                self._master_sector_found = True
                return 1.0
            return 0.0
        except Exception as exc:
            log.debug("Hikvision detect() error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        if self._master_sector_found:
            return "Hikvision (master sector found; version not yet determined)"
        return ""

    # ── list_recordings ───────────────────────────────────────────────────────

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        """
        Index entries carry no frames themselves; they are applied inside carve() so every
        recovered stream is tied to its block. Nothing is returned here.
        """
        note = (
            "Hikvision HIKBTREE entries (Han 2015) are read during carving and assigned to "
            "the streams found in each data block; no frames are listed from the index alone."
        )
        log.info(note)
        return [], note

    # ── carve (standards-based) ───────────────────────────────────────────────

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Carve video from a Hikvision disk.

        If the master sector parses and passes the paper's arithmetic self-consistency checks
        (Han 2015), only the data blocks it lists are scanned, and each block inherits the
        channel and start/end window from its HIKBTREE entry when the entry survived (a
        formatted or overwritten disk loses them; the video usually remains — Han 2015 §3.2).
        Blocks without a usable entry are still carved, as unindexed footage with no camera or
        window. If the master sector is missing or inconsistent, the whole image is carved.

        Inside blocks the standards-based stream carver is used (MPEG-PS / H.264 Annex B), so
        per-frame timestamps stay unavailable; the window is block-level only. All results are
        UNCERTAIN until ffprobe decodes the export (then PARTIAL, never COMPLETE).
        """
        mm, total = img.mm, img.size
        ms = find_master_sector(mm, total)
        problems = master_sector_problems(ms) if ms is not None else ["no master sector"]
        if ms is None or problems:
            frames, note = carve_standard_streams(img, "hikvision", progress_cb)
            return frames, note + (
                " Master sector not usable for indexed carving (" + "; ".join(problems) + ")."
            )

        entries, method = read_entries(mm, ms, total)
        by_block: dict[int, list] = {}
        for e in entries:
            by_block.setdefault(e.block_index, []).append(e)

        regions: list[CarveRegion] = []
        indexed = ambiguous = unindexed = 0
        for idx in range(ms.block_count):
            start = ms.block_offset(idx)
            if start >= total:
                break
            stop = min(total, start + ms.block_size)
            live = [e for e in by_block.get(idx, []) if e.has_video]
            if len(live) == 1:
                e = live[0]
                regions.append(CarveRegion(start, stop, camera=e.channel or 0,
                                           window_start=e.start, window_end=e.end))
                indexed += 1
            else:
                # No entry, an overwritten entry, or several entries for one block (recording
                # paused / channel changed): the channel and window cannot be assigned safely.
                regions.append(CarveRegion(start, stop))
                if live:
                    ambiguous += 1
                else:
                    unindexed += 1

        frames, note = carve_standard_streams(img, "hikvision", progress_cb, regions=regions)
        idr_blocks = idr_total = 0
        idr_first = idr_last = None
        for r in regions:
            times = read_idr_times(mm, r.start, ms.block_size, total)
            if times:
                idr_blocks += 1
                idr_total += len(times)
                idr_first = min(times) if idr_first is None else min(idr_first, min(times))
                idr_last = max(times) if idr_last is None else max(idr_last, max(times))
        if ms.extra_offset:
            note += (f" The file system is shifted by {ms.extra_offset} bytes in this image (signature at "
                     f"{HIKV_MASTER_SECTOR_OFFSET + ms.extra_offset:#x}); all pointers were adjusted.")
        if idr_total:
            from datetime import datetime, timezone
            note += (f" IDR tables (OFNI, time field only) found in {idr_blocks} block(s): {idr_total} key-frame times "
                     f"from {datetime.fromtimestamp(idr_first, tz=timezone.utc):%Y-%m-%d %H:%M} to "
                     f"{datetime.fromtimestamp(idr_last, tz=timezone.utc):%Y-%m-%d %H:%M} UTC (informational).")
        note += (
            f" Entries read by: {method}."
            f" Index: {len(entries)} HIKBTREE data-block entries read; {indexed} block(s) got a "
            f"camera/time window, {ambiguous} block(s) had several entries (not assigned), "
            f"{unindexed} block(s) had no usable entry (unindexed/deleted footage)."
        )
        return frames, note
