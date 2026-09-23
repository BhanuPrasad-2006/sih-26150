"""
hikvision.py — Hikvision DVR/NVR brand plugin.

What is implemented in v1:
  - detect():          Check master sector at 0x200 for b'HIKVISION@HANGZHOU'.
                       Returns 1.0 on match, 0.0 otherwise.
  - list_recordings(): NOT IMPLEMENTED — HIKB-TREE entry layout is not yet verified.
                       Returns ([], "not implemented") immediately.
  - carve():           Standards-based stream carving (2026-09 rewrite): finds
                       contiguous MPEG program streams (ISO/IEC 13818-1) and
                       H.264 Annex B streams (ITU-T H.264) by their PUBLIC
                       structure, with exact run extents. Verified end-to-end
                       with real ffmpeg-encoded video (see backend/tests/manual/).
                       No Hikvision-specific layout is parsed (channel, timestamps
                       and HIKB-TREE are unverified), and every result is UNCERTAIN
                       until ffprobe decodes the export (then PARTIAL, never COMPLETE).

See docs/format_sheets/hikvision.md for full status table.

Sources:
  [Han2015]   Han, Jeong, Lee (2015). ICDF2C, Springer.
  [MDPI2025]  MDPI Information 16(11):983, 2025.
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
from backend.plugins.stream_carver import carve_standard_streams

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

            window = img.mm[HIKV_MASTER_SECTOR_OFFSET : HIKV_MASTER_SECTOR_OFFSET + 512]
            if HIKV_MASTER_SECTOR_MAGIC in window:
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
        HIKB-TREE index parsing is NOT implemented in v1.
        The exact byte layout of index entries is not yet verified.
        See docs/format_sheets/hikvision.md §2 for details.
        """
        note = (
            "Hikvision HIKB-TREE index parsing is not implemented in v1. "
            "Index entry layout is unverified (TO VERIFY — see "
            "docs/format_sheets/hikvision.md §2). Using carving only."
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
        Standards-based stream carving (see backend/plugins/stream_carver.py).
        Nothing Hikvision-specific is parsed — the HIKB-TREE index is unverified —
        so channel and timestamps are unavailable (camera=0, timestamp=None), and
        every result is UNCERTAIN until ffprobe decodes the exported bytes.
        """
        return carve_standard_streams(img, "hikvision", progress_cb)
