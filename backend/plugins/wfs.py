"""
wfs.py — Xiongmai / WFS (WFS 0.1, WFS 0.2) brand plugin.

Supports the widespread Xiongmai (XM / XMeye) and white-label generic Chinese DVRs
commonly encountered in Indian surveillance forensics.

Layout:
  - Superblock / volume header: begins with 'WFS0.1' or 'WFS0.2'.
  - Frame / track records: prefixed with 'WFS' headers containing channel ID,
    32-bit Unix epoch timestamp, frame size, and raw H.264/H.265 payload.
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    WFS_DETECT_SCAN_BYTES,
    WFS_FRAME_HEADER_MAGIC,
    WFS_MAGIC_GEN,
    WFS_MAGIC_V01,
    WFS_MAGIC_V02,
    WFS_MIN_YEAR,
)
from backend.plugins.stream_carver import carve_standard_streams

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

# Minimum header size for WFS frame descriptor (16 bytes)
_WFS_FRAME_HDR_SIZE = 16


def parse_wfs_epoch_timestamp(epoch_val: int) -> Optional[datetime]:
    """Validate and convert a 32-bit Unix epoch integer to UTC datetime."""
    try:
        # Sanity check: between 2005 and 2035
        if 1104537600 <= epoch_val <= 2082758400:
            return datetime.fromtimestamp(epoch_val, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


class WFSPlugin(BrandPlugin):
    """Plugin for Xiongmai / WFS 0.1 / WFS 0.2 white-label DVR storage."""

    name = "wfs"
    display_name = "Xiongmai / WFS (White-label & Generic DVRs)"

    def __init__(self) -> None:
        self._version = ""

    def detect(self, img: "EvidenceImage") -> float:
        """
        Scan disk prefix for WFS superblock signature.
        Returns 0.0 to 1.0 confidence.
        """
        try:
            mm = img.mm
            limit = min(img.size, WFS_DETECT_SCAN_BYTES)

            # Check sector 0 / 1 directly
            hdr_0 = mm[0:16]
            if hdr_0.startswith(WFS_MAGIC_V01):
                self._version = "WFS 0.1"
                return 1.0
            if hdr_0.startswith(WFS_MAGIC_V02):
                self._version = "WFS 0.2"
                return 1.0

            # Rolling scan across detection window
            pos_v01 = mm.find(WFS_MAGIC_V01, 0, limit)
            if pos_v01 != -1:
                self._version = "WFS 0.1"
                return 0.90

            pos_v02 = mm.find(WFS_MAGIC_V02, 0, limit)
            if pos_v02 != -1:
                self._version = "WFS 0.2"
                return 0.90

            pos_gen = mm.find(WFS_MAGIC_GEN, 0, limit)
            if pos_gen != -1:
                self._version = "WFS Generic"
                return 0.70

            return 0.0
        except Exception as exc:
            log.warning("WFS detect error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        return self._version or "WFS 0.x"

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        # WFS track/block indexes are extracted during carving
        return [], "WFS recordings reassembled through frame track carving."

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Scan disk for WFS frame headers with embedded timestamps and channel IDs.
        Falls back to standards-based stream carving if frame headers are fragmented.
        """
        mm = img.mm
        total = img.size
        frames: list[RawFrame] = []
        search_from = 0
        counter = 0

        try:
            while search_from + _WFS_FRAME_HDR_SIZE < total:
                pos = mm.find(WFS_FRAME_HEADER_MAGIC, search_from)
                if pos == -1:
                    break

                if pos + _WFS_FRAME_HDR_SIZE > total:
                    break

                # Inspect 16-byte header:
                # [0:3] = b"WFS"
                # [3]   = subversion / type
                # [4]   = channel (0-based or 1-based, 0..32)
                # [5]   = frame_type (0 = keyframe / I-frame, 1 = P-frame)
                # [6:8] = reserved / flags
                # [8:12] = frame_length (u32 LE)
                # [12:16]= timestamp_epoch (u32 LE)
                hdr = mm[pos : pos + _WFS_FRAME_HDR_SIZE]
                channel = hdr[4]
                ftype = hdr[5]
                frame_len = struct.unpack("<I", hdr[8:12])[0]
                raw_epoch = struct.unpack("<I", hdr[12:16])[0]

                dt = parse_wfs_epoch_timestamp(raw_epoch)

                # Validate frame length (between 16 bytes and 10 MB) and timestamp
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
            note = f"WFS carving stopped early: {exc}"
            log.warning(note)
            return frames, note

        if frames:
            note = (
                f"WFS carving complete: {len(frames)} frames recovered with "
                "channel IDs and synchronized UTC timestamps."
            )
            return frames, note

        # Fallback to standards-based carving if proprietary headers were wiped
        fallback_frames, f_note = carve_standard_streams(img, self.name, progress_cb)
        note = f"WFS headers wiped or unindexed; standard stream carver recovered: {f_note}"
        return fallback_frames, note
