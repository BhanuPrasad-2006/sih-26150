"""
hikvision.py — Hikvision DVR/NVR brand plugin.

What is implemented in v1:
  - detect():          Check master sector at 0x200 for b'HIKVISION@HANGZHOU'.
                       Returns 1.0 on match, 0.0 otherwise.
  - list_recordings(): NOT IMPLEMENTED — HIKB-TREE entry layout is not yet verified.
                       Returns ([], "not implemented") immediately.
  - carve():           EXPERIMENTAL — searches for standard H.264 NAL start codes.
                       NAL start codes appear throughout normal H.264 streams and
                       produce many false positives. All carved results are labelled
                       UNCERTAIN by the reconstructor unless ffprobe decodes them.
                       The 0xBA/0xBC firmware prefix is not searched (TO VERIFY).

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
    HIKV_NAL_START_CODE,
)

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

    # ── carve (experimental) ──────────────────────────────────────────────────

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        EXPERIMENTAL: Scan for H.264 NAL start codes (0x00000001).

        WARNING: This produces many false positives. All results are tagged with
        is_keyframe=False and will be labelled UNCERTAIN by the reconstructor unless
        ffprobe successfully decodes them.

        The 0xBA/0xBC firmware prefix is NOT searched — that claim is TO VERIFY
        (see docs/format_sheets/hikvision.md §4).
        """
        mm = img.mm
        total = img.size
        frames: list[RawFrame] = []
        search_from = 0
        found_count = 0

        try:
            while search_from < total:
                pos = mm.find(HIKV_NAL_START_CODE, search_from)
                if pos == -1:
                    break
                # We record the offset but do not attempt to parse the NAL length
                # because NAL framing for this firmware variant is TO VERIFY.
                frames.append(
                    RawFrame(
                        brand="hikvision",
                        camera=0,          # channel separation TO VERIFY
                        sequence=found_count,
                        timestamp=None,    # timestamp extraction TO VERIFY
                        disk_offset=pos,
                        frame_size=len(HIKV_NAL_START_CODE),  # placeholder
                        frame_type=0x00,
                        is_keyframe=False,
                    )
                )
                found_count += 1
                search_from = pos + len(HIKV_NAL_START_CODE)

                if progress_cb and found_count % 1000 == 0:
                    try:
                        progress_cb(search_from, total)
                    except Exception:
                        pass

        except Exception as exc:
            note = (
                f"EXPERIMENTAL Hikvision carving stopped early: {exc}. "
                "All results are UNCERTAIN — verify on a real disk."
            )
            log.warning(note)
            return frames, note

        note = (
            f"EXPERIMENTAL Hikvision carving complete: {len(frames)} NAL start-code "
            "positions found. All results are UNCERTAIN (high false-positive rate). "
            "ffprobe validation required before any result can be elevated to PARTIAL. "
            "See docs/format_sheets/hikvision.md §4."
        )
        log.info(note)
        return frames, note
