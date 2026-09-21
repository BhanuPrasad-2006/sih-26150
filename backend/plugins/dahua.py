"""
dahua.py — Dahua DVR/NVR brand plugin.

What is implemented in v1:
  - detect():          Scan for DHAV frame magic bytes → confidence score.
  - list_recordings(): NOT IMPLEMENTED (DHFS index layout not yet verified).
                       Returns ([], "not implemented") immediately.
  - carve():           Full rolling scan with mmap.find for DHAV frames.
                       Every candidate is validated against the checklist in
                       docs/format_sheets/dahua.md §2 and PRD §5.6.1.

Carving algorithm:
  1. Use mm.find(b'DHAV', search_from) — C-speed search, no Python byte loops.
  2. For each hit, read and validate the 40-byte header.
  3. Confirm the footer (b'dhav' + repeated length) at the expected position.
  4. If all checks pass, emit a RawFrame.
  5. Advance search_from past this frame; on failure advance by 4 (past the marker).

Sources:
  [FFmpeg-dhav]  FFmpeg libavformat/dhav.c
  [MDPI2025]     MDPI Information 16(11):983, 2025
  [MDPI2026]     MDPI Information 17(5):493, 2026
"""

from __future__ import annotations

import logging
import struct
import time
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import LogEvent, RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    DHAV_FOOTER_MAGIC,
    DHAV_FOOTER_OFF_LENGTH,
    DHAV_FOOTER_SIZE,
    DHAV_HEADER_MAGIC,
    DHAV_HEADER_SIZE,
    DHAV_MAX_CHANNEL,
    DHAV_MAX_FRAME_BYTES,
    DHAV_MIN_FRAME_BYTES,
    DHAV_OFF_CHANNEL,
    DHAV_OFF_FRAME_TYPE,
    DHAV_OFF_SEQUENCE,
    DHAV_OFF_TIMESTAMP_MS,
    DHAV_OFF_TIMESTAMP_S,
    DHAV_OFF_TOTAL_SIZE,
    DHAV_TS_MIN_UNIX,
    DHAV_TYPE_VIDEO_IFRAME,
    DHAV_VALID_FRAME_TYPES,
)

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)


class DahuaPlugin(BrandPlugin):
    name = "dahua"
    display_name = "Dahua"

    # Minimum number of valid DHAV frames required to return confidence >= 0.5
    _DETECT_MIN_FRAMES = 5
    # How many bytes to scan during detection (avoid scanning the whole image)
    _DETECT_SCAN_BYTES = 32 * 1024 * 1024  # 32 MB

    def __init__(self) -> None:
        self._detected_version: str = ""

    # ── detect ────────────────────────────────────────────────────────────────

    def detect(self, img: "EvidenceImage") -> float:
        """
        Scan the first _DETECT_SCAN_BYTES of the image for valid DHAV frames.
        Returns 0.0–1.0 confidence.
        """
        try:
            mm = img.mm
            mm.seek(0)
            limit = min(img.size, self._DETECT_SCAN_BYTES)
            valid_count = 0
            search_from = 0

            while search_from < limit:
                pos = mm.find(DHAV_HEADER_MAGIC, search_from, limit)
                if pos == -1:
                    break
                frame = _validate_dhav_frame(mm, pos, img.size)
                if frame is not None:
                    valid_count += 1
                    search_from = pos + frame.frame_size
                else:
                    search_from = pos + len(DHAV_HEADER_MAGIC)

            if valid_count == 0:
                return 0.0
            if valid_count >= self._DETECT_MIN_FRAMES:
                return 1.0
            # Linear ramp between 1 and _DETECT_MIN_FRAMES valid frames
            return 0.5 + 0.5 * (valid_count / self._DETECT_MIN_FRAMES)
        except Exception as exc:
            log.debug("Dahua detect() error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        return self._detected_version or "DHAV (version not yet determined)"

    # ── list_recordings ───────────────────────────────────────────────────────

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        """
        DHFS index parsing is NOT implemented in v1.
        The DHFS superblock and index entry layout are not yet verified on a real disk.
        See docs/format_sheets/dahua.md §1 for details.
        """
        note = (
            "Dahua DHFS index parsing is not implemented in v1. "
            "The file-system index layout is unverified (TO VERIFY — see "
            "docs/format_sheets/dahua.md §1). Using carving only."
        )
        log.info(note)
        return [], note

    # ── carve ─────────────────────────────────────────────────────────────────

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Scan the full image for DHAV frames using mmap.find (C-speed).
        See module docstring for algorithm.
        """
        mm = img.mm
        total = img.size
        frames: list[RawFrame] = []
        rejected_count = 0
        search_from = 0

        try:
            while search_from < total:
                pos = mm.find(DHAV_HEADER_MAGIC, search_from)
                if pos == -1:
                    break

                frame = _validate_dhav_frame(mm, pos, total)
                if frame is not None:
                    frames.append(frame)
                    search_from = pos + frame.frame_size
                else:
                    rejected_count += 1
                    search_from = pos + len(DHAV_HEADER_MAGIC)

                if progress_cb and (len(frames) + rejected_count) % 500 == 0:
                    try:
                        progress_cb(search_from, total)
                    except Exception:
                        pass
        except Exception as exc:
            note = f"Dahua carving stopped early due to error: {exc}"
            log.warning(note)
            return frames, note

        note = (
            f"Dahua carving complete: {len(frames)} valid DHAV frames found, "
            f"{rejected_count} candidates rejected."
        )
        log.info(note)
        return frames, note


# ── Frame validation ──────────────────────────────────────────────────────────

def _validate_dhav_frame(mm: object, pos: int, image_size: int) -> Optional[RawFrame]:
    """
    Validate a DHAV candidate at byte offset *pos*.

    Checks (per docs/format_sheets/dahua.md §2, PRD §5.6.1):
      1. Enough bytes remain for a minimum header.
      2. Frame type byte ∈ DHAV_VALID_FRAME_TYPES.
      3. Total frame length is plausible (DHAV_MIN_FRAME_BYTES – DHAV_MAX_FRAME_BYTES).
      4. Frame does not extend past the end of the image.
      5. Footer b'dhav' is at the expected position.
      6. Footer length field equals the header length field.
      7. Channel number ≤ DHAV_MAX_CHANNEL.
      8. Timestamp is sane (not before 2000, not in the future).

    Returns a RawFrame on success, None on any failure.
    """
    try:
        # Bounds: we need at least DHAV_HEADER_SIZE bytes
        if pos + DHAV_HEADER_SIZE > image_size:
            return None

        header = mm[pos : pos + DHAV_HEADER_SIZE]

        # 1. Magic already matched by mmap.find — double-check for safety
        if header[:4] != DHAV_HEADER_MAGIC:
            return None

        # 2. Frame type
        frame_type = header[DHAV_OFF_FRAME_TYPE]
        if frame_type not in DHAV_VALID_FRAME_TYPES:
            return None

        # 3. Total frame size
        total_size = struct.unpack_from("<I", header, DHAV_OFF_TOTAL_SIZE)[0]
        if not (DHAV_MIN_FRAME_BYTES <= total_size <= DHAV_MAX_FRAME_BYTES):
            return None

        # 4. Frame fits in image
        if pos + total_size > image_size:
            return None

        # 5 & 6. Footer validation
        footer_pos = pos + total_size - DHAV_FOOTER_SIZE
        footer = mm[footer_pos : footer_pos + DHAV_FOOTER_SIZE]
        if len(footer) < DHAV_FOOTER_SIZE:
            return None
        if footer[:4] != DHAV_FOOTER_MAGIC:
            return None
        footer_length = struct.unpack_from("<I", footer, DHAV_FOOTER_OFF_LENGTH)[0]
        if footer_length != total_size:
            return None

        # 7. Channel
        channel = struct.unpack_from("<H", header, DHAV_OFF_CHANNEL)[0]
        if channel > DHAV_MAX_CHANNEL:
            return None

        # 8. Timestamp sanity
        ts_seconds = struct.unpack_from("<I", header, DHAV_OFF_TIMESTAMP_S)[0]
        ts_ms       = struct.unpack_from("<H", header, DHAV_OFF_TIMESTAMP_MS)[0]
        now_unix    = int(time.time())
        if ts_seconds < DHAV_TS_MIN_UNIX:
            return None
        if ts_seconds > now_unix + 86400:  # more than 1 day in the future
            return None

        # Build timestamp (assumed UTC; epoch and timezone are Proposed)
        try:
            timestamp = datetime.fromtimestamp(ts_seconds, tz=timezone.utc).replace(
                microsecond=ts_ms * 1000
            )
        except (OSError, OverflowError, ValueError):
            return None

        sequence = struct.unpack_from("<I", header, DHAV_OFF_SEQUENCE)[0]
        is_keyframe = frame_type == DHAV_TYPE_VIDEO_IFRAME

        return RawFrame(
            brand="dahua",
            camera=channel,
            sequence=sequence,
            timestamp=timestamp,
            disk_offset=pos,
            frame_size=total_size,
            frame_type=frame_type,
            is_keyframe=is_keyframe,
        )

    except Exception:
        return None
