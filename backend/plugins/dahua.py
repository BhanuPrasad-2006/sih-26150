"""
dahua.py — Dahua DVR/NVR brand plugin.

What is implemented in v1:
  - detect():          A valid DHFS 4.1 partition table, or DHAV frames → confidence.
  - list_recordings(): Reads the DHFS 4.1 disk index (dahua_dhfs.py; Wullen 2025 + Batista's
                       extractor, L2 in docs/format_verification.md) and reassembles each
                       recording from its descriptor chain, with camera and start times.
  - carve():           Full rolling scan with mmap.find for DHAV frames, validated per
                       docs/format_sheets/dahua.md §2. When a DHFS index exists, frames inside
                       indexed clusters are left to the index, so what carve() returns is the
                       footage OUTSIDE indexed recordings (deleted, free or slack space).
                       Not validated on a real Dahua disk.

Carving algorithm:
  1. Use mm.find(b'DHAV', search_from) — C-speed search, no Python byte loops.
  2. For each hit, read and validate the (variable-length) header.
  3. Confirm the trailer (b'dhav' + repeated length) at the expected position
     (a carving-precision heuristic — see constants.py DHAV_TRAILER_MAGIC).
  4. If all checks pass, emit a RawFrame.
  5. Advance search_from past this frame; on failure advance by 4 (past the marker).

2026-09 correction: the header/type constants used here were re-derived from
FFmpeg's actual libavformat/dhav.c source after an end-to-end test with a real
H.264 recording proved the previous constants wrong (frame-type mapping was
backwards, channel field was the wrong width, header size was wrongly assumed
fixed). See constants.py and docs/format_sheets/dahua.md §2 for details.

Sources:
  [FFmpeg-dhav]  FFmpeg libavformat/dhav.c
  [MDPI2025]     MDPI Information 16(11):983, 2025
  [MDPI2026]     MDPI Information 17(5):493, 2026
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import LogEvent, RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.dahua_dhfs import iter_recordings, read_partitions
from backend.plugins.constants import (
    CPPLUS_IDENTIFYING_MARKERS,
    DHAV_DATE_YEAR_MIN,
    DHAV_EXT_HEADER_SIZE,
    DHAV_FIXED_HEADER_SIZE,
    DHAV_HEADER_MAGIC,
    DHAV_MAX_CHANNEL,
    DHAV_MAX_FRAME_BYTES,
    DHAV_MIN_FRAME_BYTES,
    DHAV_MIN_HEADER_SIZE,
    DHAV_OFF_CHANNEL,
    DHAV_OFF_DATE,
    DHAV_OFF_EXT_LENGTH,
    DHAV_OFF_FRAME_TYPE,
    DHAV_OFF_SEQUENCE,
    DHAV_OFF_TOTAL_SIZE,
    DHAV_TRAILER_MAGIC,
    DHAV_TRAILER_OFF_LENGTH,
    DHAV_TRAILER_SIZE,
    DHAV_TYPE_PARTIAL,
    DHAV_TYPE_VIDEO_KEYFRAME,
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
            dhfs_ok = bool(read_partitions(mm, img.size))

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

            if valid_count == 0 and not dhfs_ok:
                return 0.0
            # If CP Plus brand strings are present, Dahua yields primary brand attribution to CP Plus stub
            for marker in CPPLUS_IDENTIFYING_MARKERS:
                if mm.find(marker, 0, limit) != -1:
                    return 0.90

            if dhfs_ok or valid_count >= self._DETECT_MIN_FRAMES:
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
        Read the DHFS 4.1 disk index (Wullen 2025 + Batista's extractor; see
        docs/format_verification.md): partition table, boot sector, descriptor table, and follow
        each recording's cluster chain. Every fragment becomes one RawFrame carrying the
        recording's camera, the fragment's start time, and the recording's stream_id, so the
        reconstructor keeps a recording together even across time gaps. Returns [] if the disk
        has no valid DHFS 4.1 index (then only carving applies).
        """
        frames: list[RawFrame] = []
        try:
            parts = read_partitions(img.mm, img.size)
            for part in parts:
                for rec in iter_recordings(img.mm, img.size, part):
                    for n, fr in enumerate(rec.fragments):
                        frames.append(RawFrame(
                            brand="dahua", camera=rec.camera, sequence=n + 1,
                            timestamp=(fr.begin if n else rec.begin),
                            disk_offset=fr.offset, frame_size=fr.size,
                            frame_type=0, is_keyframe=False, stream_id=rec.stream_id,
                        ))
        except Exception as exc:
            note = f"Dahua DHFS 4.1 index could not be read ({exc}); carving only."
            log.warning(note)
            return [], note
        if not parts:
            return [], "No DHFS 4.1 index found on this disk (carving only)."
        n_rec = len({f.stream_id for f in frames})
        return frames, (
            f"Dahua DHFS 4.1 index: {len(parts)} partition(s), {n_rec} recording(s), "
            f"{len(frames)} fragment(s) reassembled from descriptor chains."
        )

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
        indexed = _indexed_ranges(img)
        skipped_indexed = 0

        try:
            while search_from < total:
                pos = mm.find(DHAV_HEADER_MAGIC, search_from)
                if pos == -1:
                    break

                frame = _validate_dhav_frame(mm, pos, total)
                if frame is not None:
                    if _in_ranges(indexed, pos):
                        skipped_indexed += 1   # already reported through the DHFS index
                    else:
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
        if indexed:
            note += (
                f" {skipped_indexed} frame(s) inside indexed clusters were left to the DHFS index; "
                "the frames above lie OUTSIDE indexed recordings (deleted, free, or slack space)."
            )
        log.info(note)
        return frames, note


# ── DHFS index helpers ────────────────────────────────────────────────────────

def _indexed_ranges(img) -> list[tuple[int, int]]:
    """Sorted byte ranges of every cluster that belongs to an indexed recording."""
    try:
        ranges: list[tuple[int, int]] = []
        for part in read_partitions(img.mm, img.size):
            for rec in iter_recordings(img.mm, img.size, part):
                ranges.extend((fr.offset, fr.offset + part.cluster_size) for fr in rec.fragments)
        ranges.sort()
        return ranges
    except Exception:
        return []


def _in_ranges(ranges: list[tuple[int, int]], pos: int) -> bool:
    if not ranges:
        return False
    import bisect
    i = bisect.bisect_right(ranges, (pos, float("inf"))) - 1
    return i >= 0 and ranges[i][0] <= pos < ranges[i][1]


# ── Frame validation ──────────────────────────────────────────────────────────

def _decode_dhav_date(raw: int) -> Optional[datetime]:
    """
    Decode DHAV's packed-bitfield date (offset 0x10). This is NOT a Unix
    epoch — it is a bit-packed calendar reading of the device's own clock:
    sec[0:6] min[6:12] hour[12:17] day[17:22] month[22:26] year[26:32]+2000.
    Verified against FFmpeg libavformat/dhav.c get_timeinfo().

    Returns None if the bits don't form a valid calendar date/time (a cheap
    extra rejection of coincidental "DHAV" matches in non-Dahua data, and of
    a clock that was never set).
    """
    sec = raw & 0x3F
    minute = (raw >> 6) & 0x3F
    hour = (raw >> 12) & 0x1F
    day = (raw >> 17) & 0x1F
    month = (raw >> 22) & 0x0F
    year = ((raw >> 26) & 0x3F) + 2000
    try:
        return datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc)
    except ValueError:
        return None


def _validate_dhav_frame(mm: object, pos: int, image_size: int) -> Optional[RawFrame]:
    """
    Validate a DHAV candidate at byte offset *pos*.

    Checks (per docs/format_sheets/dahua.md §2, PRD §5.6.1):
      1. Enough bytes remain for the minimum (non-partial) header.
      2. Frame type byte ∈ DHAV_VALID_FRAME_TYPES, and not the "partial"
         continuation type (0xF1), which carries no independent payload.
      3. Channel number ≤ DHAV_MAX_CHANNEL.
      4. Total frame length is plausible (DHAV_MIN_FRAME_BYTES – DHAV_MAX_FRAME_BYTES).
      5. Frame does not extend past the end of the image.
      6. Packed date bitfield decodes to a sane calendar timestamp
         (not before DHAV_DATE_YEAR_MIN, not more than 1 day in the future).
      7. Trailer b'dhav' + repeated length is at the expected position
         (carving-precision heuristic — see constants.py DHAV_TRAILER_MAGIC).

    Returns a RawFrame on success, None on any failure.
    """
    try:
        # Bounds: we need at least the minimum (non-partial) header
        if pos + DHAV_MIN_HEADER_SIZE > image_size:
            return None

        header = mm[pos : pos + DHAV_MIN_HEADER_SIZE]

        # 1. Magic already matched by mmap.find — double-check for safety
        if header[:4] != DHAV_HEADER_MAGIC:
            return None

        # 2. Frame type — reject the partial/continuation marker (no payload)
        frame_type = header[DHAV_OFF_FRAME_TYPE]
        if frame_type not in DHAV_VALID_FRAME_TYPES or frame_type == DHAV_TYPE_PARTIAL:
            return None

        # 3. Channel (1 byte — NOT 2, corrected 2026-09)
        channel = header[DHAV_OFF_CHANNEL]
        if channel > DHAV_MAX_CHANNEL:
            return None

        # 4. Total frame size
        total_size = struct.unpack_from("<I", header, DHAV_OFF_TOTAL_SIZE)[0]
        if not (DHAV_MIN_FRAME_BYTES <= total_size <= DHAV_MAX_FRAME_BYTES):
            return None
        ext_length = header[DHAV_OFF_EXT_LENGTH]
        if DHAV_MIN_HEADER_SIZE + ext_length + DHAV_TRAILER_SIZE > total_size:
            return None

        # 5. Frame fits in image
        if pos + total_size > image_size:
            return None

        # 6. Packed date/time sanity
        date_raw = struct.unpack_from("<I", header, DHAV_OFF_DATE)[0]
        timestamp = _decode_dhav_date(date_raw)
        if timestamp is None:
            return None
        if timestamp.year < DHAV_DATE_YEAR_MIN:
            return None
        if timestamp > datetime.now(tz=timezone.utc) + timedelta(days=1):
            return None
        # Sub-second field (offset 0x14): meaning is approximate (not
        # strictly milliseconds) — clamp so datetime.replace() never raises.
        subsecond = struct.unpack_from("<H", header, DHAV_FIXED_HEADER_SIZE)[0]
        timestamp = timestamp.replace(microsecond=min(subsecond, 999) * 1000)

        # 7. Trailer validation (carving-precision heuristic)
        trailer_pos = pos + total_size - DHAV_TRAILER_SIZE
        trailer = mm[trailer_pos : trailer_pos + DHAV_TRAILER_SIZE]
        if len(trailer) < DHAV_TRAILER_SIZE:
            return None
        if trailer[:4] != DHAV_TRAILER_MAGIC:
            return None
        trailer_length = struct.unpack_from("<I", trailer, DHAV_TRAILER_OFF_LENGTH)[0]
        if trailer_length != total_size:
            return None

        sequence = struct.unpack_from("<I", header, DHAV_OFF_SEQUENCE)[0]
        is_keyframe = frame_type == DHAV_TYPE_VIDEO_KEYFRAME

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
