"""
honeywell.py — Honeywell NVR brand plugin (layout from a published paper).

SOURCE AND LIMITS
=================
The on-disk record format used here comes from ONE published analysis:
Yoon & Hwang, "Forensic analysis of video data deletion and recovery in
Honeywell surveillance file system", arXiv:2605.07430 (May 2026), which
reverse-engineered a single Honeywell HN35080200 NVR by binary diffing.
Neither the paper nor this project validates the layout on other Honeywell
models, and this project has not tested it on a real Honeywell disk. The
paper itself recovered video by extracting from a record header to the
next 20-byte zero delimiter — the same thing carve() does, with structure
checks.

WHAT IS IMPLEMENTED
===================
Video data is a sequence of records, each a 20-byte "Custom Header"
followed by H.264 Annex B data (paper §5.4.6):

    [0]     type: 0x82 = IDR record, 0x02 = non-IDR record
    [1:4]   80 01 00 (fixed)
    [4:6]   width  (u16 LE)      [6:8] height (u16 LE)
    [8:12]  payload length (u32 LE)
    [12:20] Unix time in microseconds (u64 LE)
    then    00 00 00 01 <NAL header> ...

A channel's records are followed by 20 zero bytes ("End of Channel Data").
carve() locates records by this structure (not by offset), so it works on
deleted/formatted disks where the metadata lists are gone (paper §7).

NOT IMPLEMENTED: the Video Block/Channel Lists and Record State index. The
camera channel lives in the Channel List, so it is not recoverable by
carving; each contiguous on-disk stream is reported separately as camera 0.
"""

from __future__ import annotations

import logging
import re
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, NamedTuple, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    H264_VALID_NAL_TYPES,
    HW_DETECT_MIN_RECORDS,
    HW_DETECT_REGION_BYTES,
    HW_DETECT_WHOLE_IMAGE_MAX,
    HW_GPT_SECTOR,
    HW_MAX_TS_BACKSTEP_US,
    HW_REC_FIXED,
    HW_REC_HEADER_SIZE,
    HW_REC_MAX_DIM,
    HW_REC_MAX_PAYLOAD,
    HW_REC_MIN_DIM,
    HW_REC_TYPE_IDR,
    HW_REC_TYPE_NONIDR,
    HW_VIDEO_DATA_OFFSET,
)

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_TS_MIN_US = int(datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000
_HEADER_RE = re.compile(rb"[\x82\x02]\x80\x01\x00")
_RESYNC_WINDOW = 64 * 1024
_UNVERIFIED_ASCII_MARKERS = (b"HONEYWELL", b"Honeywell")
_STRING_HIT_CONFIDENCE = 0.15  # weak hint only, below the scan threshold
_CHAIN_CONFIDENCE = 0.9        # structure verified against the paper, single model


class _Record(NamedTuple):
    pos: int          # header start
    rtype: int
    width: int
    height: int
    length: int
    ts_us: int

    @property
    def payload_start(self) -> int:
        return self.pos + HW_REC_HEADER_SIZE


def _valid_record_at(mm, pos: int, size: int) -> Optional[_Record]:
    """Return the record whose header starts at *pos*, or None if it isn't structurally valid."""
    if pos < 0 or pos + HW_REC_HEADER_SIZE + 5 > size:
        return None
    hdr = mm[pos : pos + HW_REC_HEADER_SIZE + 5]
    rtype = hdr[0]
    if rtype not in (HW_REC_TYPE_IDR, HW_REC_TYPE_NONIDR) or hdr[1:4] != HW_REC_FIXED:
        return None
    width, height, length, ts_us = struct.unpack_from("<HHIQ", hdr, 4)
    if not (HW_REC_MIN_DIM <= width <= HW_REC_MAX_DIM and HW_REC_MIN_DIM <= height <= HW_REC_MAX_DIM):
        return None
    if not (0 < length <= HW_REC_MAX_PAYLOAD):
        return None
    now_us = int(time.time()) * 1_000_000
    if not (_TS_MIN_US <= ts_us <= now_us + 86_400 * 1_000_000):
        return None
    # Payload must open with an Annex B start code and a plausible NAL header.
    body = hdr[HW_REC_HEADER_SIZE:]
    if body[:4] == b"\x00\x00\x00\x01":
        nal = body[4]
    elif body[:3] == b"\x00\x00\x01":
        nal = body[3]
    else:
        return None
    nal_type = nal & 0x1F
    if (nal & 0x80) or nal_type not in H264_VALID_NAL_TYPES:
        return None
    if rtype == HW_REC_TYPE_IDR and nal_type not in (5, 6, 7, 8, 9):
        return None
    if rtype == HW_REC_TYPE_NONIDR and nal_type not in (1, 2, 3, 4, 6, 9):
        return None
    return _Record(pos, rtype, width, height, length, ts_us)


def _next_record(mm, after: _Record, size: int) -> tuple[Optional[_Record], int, bool]:
    """
    Find the record following *after*. Returns (next_record, payload_end, length_consistent).

    Fast path: the next header sits exactly where the length field says. Otherwise
    resynchronise to the next valid header within a bounded window and treat the
    bytes up to it as this record's payload (length-agnostic, like the paper's own
    "extract to the next header/delimiter" recovery).
    """
    expected_end = after.payload_start + after.length
    nxt = _valid_record_at(mm, expected_end, size) if expected_end < size else None
    if nxt is not None:
        return nxt, expected_end, True
    if expected_end <= size:
        # A 20-byte zero delimiter or end of image right after the payload: stream ends here.
        tail = mm[expected_end : expected_end + 20]
        if len(tail) < 20 or tail == b"\x00" * 20:
            return None, expected_end, True
    # Length field didn't land on a header: resync.
    search_from = after.payload_start + 5
    limit = min(size, max(expected_end, search_from) + _RESYNC_WINDOW)
    pos = search_from
    while pos < limit:
        m = _HEADER_RE.search(mm, pos, limit)
        if m is None:
            break
        cand = _valid_record_at(mm, m.start(), size)
        if cand is not None:
            return cand, m.start(), False
        pos = m.start() + 1
    # No later header anywhere nearby: this is the stream's final record; trust its length.
    return None, min(expected_end, size), True


def _walk_stream(mm, first: _Record, size: int) -> tuple[list[tuple[_Record, int]], int, int]:
    """Walk consecutive records. Returns ([(record, payload_end)], end_pos, length_mismatches)."""
    out: list[tuple[_Record, int]] = []
    mismatches = 0
    cur: Optional[_Record] = first
    last_ts = None
    end_pos = first.pos
    while cur is not None:
        if last_ts is not None and cur.ts_us < last_ts - HW_MAX_TS_BACKSTEP_US:
            break
        nxt, payload_end, consistent = _next_record(mm, cur, size)
        if payload_end > size:
            break
        if not consistent:
            mismatches += 1
        out.append((cur, payload_end))
        last_ts = cur.ts_us
        end_pos = payload_end
        cur = nxt
    return out, end_pos, mismatches


def _find_streams(mm, size: int, start: int, stop: int, max_streams: Optional[int] = None):
    """Yield (records_with_ends, end_pos, mismatches) for each stream found in [start, stop)."""
    pos = start
    found = 0
    while pos < stop:
        m = _HEADER_RE.search(mm, pos, stop)
        if m is None:
            return
        first = _valid_record_at(mm, m.start(), size)
        if first is None:
            pos = m.start() + 1
            continue
        recs, end_pos, mism = _walk_stream(mm, first, size)
        yield recs, end_pos, mism
        found += 1
        if max_streams is not None and found >= max_streams:
            return
        pos = max(end_pos, m.start() + HW_REC_HEADER_SIZE)


def _partition1_start(mm, size: int) -> Optional[int]:
    """Byte offset of GPT partition 1, or None if no valid GPT (paper §5.1)."""
    if size < 3 * HW_GPT_SECTOR:
        return None
    hdr = mm[HW_GPT_SECTOR : HW_GPT_SECTOR + 92]
    if hdr[:8] != b"EFI PART":
        return None
    entries_lba = struct.unpack_from("<Q", hdr, 72)[0]
    entry_size = struct.unpack_from("<I", hdr, 84)[0]
    if entry_size < 128 or entries_lba == 0:
        return None
    off = entries_lba * HW_GPT_SECTOR
    if off + entry_size > size:
        return None
    entry = mm[off : off + entry_size]
    if entry[:16] == b"\x00" * 16:
        return None
    first_lba = struct.unpack_from("<Q", entry, 32)[0]
    return first_lba * HW_GPT_SECTOR


def _ts_to_datetime(ts_us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=ts_us)


class HoneywellPlugin(BrandPlugin):
    name = "honeywell"
    display_name = "Honeywell NVR (paper-derived layout, unvalidated on hardware)"

    def __init__(self) -> None:
        self._found_structure = False

    # ── detect ────────────────────────────────────────────────────────────────

    def detect(self, img: "EvidenceImage") -> float:
        """
        Look for a chain of >= HW_DETECT_MIN_RECORDS valid Honeywell records:
        at partition 1's video-data offset (from the GPT, paper §5.1/§5.4.6) and,
        for images up to 256 MiB, anywhere in the image. Returns 0.9 on a chain,
        0.15 on a bare vendor string, else 0.0.
        """
        try:
            mm, size = img.mm, img.size
            regions: list[tuple[int, int]] = []
            p1 = _partition1_start(mm, size)
            if p1 is not None:
                start = p1 + HW_VIDEO_DATA_OFFSET
                if start < size:
                    regions.append((start, min(size, start + HW_DETECT_REGION_BYTES)))
            if size <= HW_DETECT_WHOLE_IMAGE_MAX:
                regions.append((0, size))
            for start, stop in regions:
                for recs, _end, _m in _find_streams(mm, size, start, stop, max_streams=8):
                    if len(recs) >= HW_DETECT_MIN_RECORDS:
                        self._found_structure = True
                        return _CHAIN_CONFIDENCE

            limit = min(size, 32 * 1024 * 1024)
            for marker in _UNVERIFIED_ASCII_MARKERS:
                if mm.find(marker, 0, limit) != -1:
                    return _STRING_HIT_CONFIDENCE
            return 0.0
        except Exception as exc:
            log.debug("Honeywell detect() error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        if self._found_structure:
            return "Honeywell NVR (record layout per arXiv:2605.07430; single-model analysis)"
        return ""

    # ── list_recordings ───────────────────────────────────────────────────────

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        note = (
            "Honeywell Video Block/Channel List index parsing is not implemented — "
            "recovery uses record carving, which also works after format/expiration "
            "(paper §7). Camera channel is therefore unavailable."
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
        Carve Honeywell records by structure. Each on-disk stream becomes its own
        stream_id. A stream is exported from its first IDR record so the output
        starts with SPS/PPS/IDR and is decodable; earlier non-IDR records (e.g. a
        stream whose start was overwritten) are dropped.
        """
        if img is None or getattr(img, "mm", None) is None:
            return [], "Honeywell carving is detection only (unverified layout)"
        mm, size = img.mm, img.size
        frames: list[RawFrame] = []
        streams = 0
        mismatches_total = 0
        dropped_leading = 0
        counter = 0

        try:
            pos = 0
            while pos < size:
                m = _HEADER_RE.search(mm, pos)
                if m is None:
                    break
                first = _valid_record_at(mm, m.start(), size)
                if first is None:
                    pos = m.start() + 1
                    continue
                recs, end_pos, mism = _walk_stream(mm, first, size)
                idr_idx = next((i for i, (r, _e) in enumerate(recs) if r.rtype == HW_REC_TYPE_IDR), None)
                if idr_idx is not None:
                    dropped_leading += idr_idx
                    mismatches_total += mism
                    for r, payload_end in recs[idr_idx:]:
                        frames.append(RawFrame(
                            brand="honeywell", camera=0, sequence=counter,
                            timestamp=_ts_to_datetime(r.ts_us),
                            disk_offset=r.payload_start,
                            frame_size=payload_end - r.payload_start,
                            frame_type=r.rtype,
                            is_keyframe=(r.rtype == HW_REC_TYPE_IDR),
                            stream_id=streams,
                        ))
                        counter += 1
                    streams += 1
                pos = max(end_pos, m.start() + HW_REC_HEADER_SIZE)
                if progress_cb:
                    try:
                        progress_cb(pos, size)
                    except Exception:
                        pass
        except Exception as exc:
            note = f"Honeywell record carving stopped early: {exc}. Results so far are UNCERTAIN."
            log.warning(note)
            return frames, note

        note = (
            f"Honeywell record carving complete: {streams} stream(s), {len(frames)} record(s). "
            f"Layout per arXiv:2605.07430 (single model, unvalidated on hardware). "
            f"{dropped_leading} leading non-IDR record(s) skipped; "
            f"{mismatches_total} record(s) where the length field did not match the next header."
        )
        log.info(note)
        return frames, note
