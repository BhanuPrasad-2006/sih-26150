"""
hanwha.py — Hanwha Vision (formerly Samsung Techwin) DVR/NVR brand plugin.

Supports Hanwha Vision and Samsung Techwin surveillance systems (SRD, HRD, PRN series)
prevalent in Indian banking, defense, and high-security installations.

Structure:
  - Superblock / volume: starts with 'SSF1.0', 'SSF2.0', or 'SEC_VIDEO' / 'SEC'.
  - Frame containers (.sec/.srf): 16-to-32 byte frame headers containing camera ID,
    frame type, frame length, and 32-bit LE Unix timestamp.
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    HANWHA_DETECT_SCAN_BYTES,
    HANWHA_FRAME_HEADER_MAGIC,
    HANWHA_MAGIC_SEC,
    HANWHA_MAGIC_SECV,
    HANWHA_MAGIC_SSF1,
    HANWHA_MAGIC_SSF2,
)
from backend.plugins.stream_carver import carve_standard_streams

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

_HANWHA_HDR_SIZE = 16


def parse_hanwha_timestamp(epoch_val: int) -> Optional[datetime]:
    """Convert 32-bit Unix epoch timestamp to UTC datetime with sanity check."""
    try:
        if 1104537600 <= epoch_val <= 2082758400:  # 2005 to 2035
            return datetime.fromtimestamp(epoch_val, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


class HanwhaPlugin(BrandPlugin):
    """Plugin for Hanwha Vision / Samsung Techwin surveillance recorders."""

    name = "hanwha"
    display_name = "Hanwha Vision / Samsung Techwin"

    def __init__(self) -> None:
        self._version = ""

    def detect(self, img: "EvidenceImage") -> float:
        """Scan disk prefix for Hanwha / Samsung SSF/SEC signatures."""
        try:
            mm = img.mm
            limit = min(img.size, HANWHA_DETECT_SCAN_BYTES)

            hdr_0 = mm[0:16]
            if hdr_0.startswith(HANWHA_MAGIC_SSF1):
                self._version = "SSF 1.0"
                return 1.0
            if hdr_0.startswith(HANWHA_MAGIC_SSF2):
                self._version = "SSF 2.0"
                return 1.0
            if hdr_0.startswith(HANWHA_MAGIC_SECV):
                self._version = "SEC Video Container"
                return 0.95

            pos_ssf = mm.find(HANWHA_MAGIC_SSF1, 0, limit)
            if pos_ssf != -1:
                self._version = "SSF 1.0"
                return 0.90

            pos_sec = mm.find(HANWHA_MAGIC_SECV, 0, limit)
            if pos_sec != -1:
                self._version = "SEC Container"
                return 0.85

            return 0.0
        except Exception as exc:
            log.warning("Hanwha detect error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        return self._version or "Hanwha / SSF"

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        return [], "Hanwha recordings parsed through SEC block carving."

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Carve Hanwha SEC records containing channel, timestamps, and H.264/H.265 frames.
        """
        mm = img.mm
        total = img.size
        frames: list[RawFrame] = []
        search_from = 0
        counter = 0

        try:
            while search_from + _HANWHA_HDR_SIZE < total:
                pos = mm.find(HANWHA_FRAME_HEADER_MAGIC, search_from)
                if pos == -1:
                    break

                if pos + _HANWHA_HDR_SIZE > total:
                    break

                # 16-byte header:
                # [0:3] = b"SEC"
                # [3]   = subversion
                # [4]   = channel (0..32)
                # [5]   = frame_type (0 = Keyframe, 1 = P-frame)
                # [6:8] = reserved
                # [8:12]= frame_length (u32 LE)
                # [12:16]= timestamp_epoch (u32 LE)
                hdr = mm[pos : pos + _HANWHA_HDR_SIZE]
                channel = hdr[4]
                ftype = hdr[5]
                frame_len = struct.unpack("<I", hdr[8:12])[0]
                raw_epoch = struct.unpack("<I", hdr[12:16])[0]

                dt = parse_hanwha_timestamp(raw_epoch)

                if dt is not None and 16 <= frame_len <= 10 * 1024 * 1024 and channel <= 32:
                    is_key = (ftype == 0)
                    frames.append(
                        RawFrame(
                            brand=self.name,
                            camera=channel,
                            sequence=counter,
                            timestamp=dt,
                            disk_offset=pos,
                            frame_size=frame_len,
                            frame_type=ftype,
                            is_keyframe=is_key,
                        )
                    )
                    counter += 1
                    search_from = pos + frame_len
                else:
                    search_from = pos + 3

                if progress_cb and counter % 500 == 0:
                    try:
                        progress_cb(search_from, total)
                    except Exception:
                        pass

        except Exception as exc:
            note = f"Hanwha carving stopped early: {exc}"
            log.warning(note)
            return frames, note

        if frames:
            return frames, f"Hanwha carving complete: {len(frames)} frames recovered with timeline sync."

        # Fallback to standards-based carving
        fallback_frames, f_note = carve_standard_streams(img, self.name, progress_cb)
        return fallback_frames, f"Hanwha SEC headers unindexed; standard stream carver recovered: {f_note}"
