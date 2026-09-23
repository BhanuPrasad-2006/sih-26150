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
import re
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    H264_MAX_PARAM_SET_BYTES,
    H264_MAX_TAIL_NAL_BYTES,
    H264_NAL_IDR,
    H264_NAL_PPS,
    H264_NAL_SLICE,
    H264_NAL_SPS,
    H264_TAIL_IDENTICAL_RUN,
    H264_VALID_NAL_TYPES,
    H264_VALID_PROFILE_IDC,
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
    MPEG_PS_MIN_ELEMENTS,
    MPEG_PS_PES_STREAM_IDS,
    MPEG_PS_VIDEO_STREAM_ID_MAX,
    MPEG_PS_VIDEO_STREAM_ID_MIN,
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

    # ── carve (standards-based) ───────────────────────────────────────────────

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Standards-based stream carving. Locates contiguous, structurally valid
        video streams in raw bytes — WITHOUT relying on any Hikvision-specific
        on-disk layout (the HIKB-TREE index is unverified):

          * MPEG program streams (ISO/IEC 13818-1): pack header + PES packet
            chain, walked by their length fields, so run extents are exact.
          * H.264 Annex B byte streams (ITU-T H.264): must open with a valid
            SPS then PPS then a slice; NAL extents follow the Annex B rules.

        Nothing Hikvision-specific is parsed, so channel, timestamps and the
        index are unavailable (camera=0, timestamp=None). Every result is
        UNCERTAIN until ffprobe/FFmpeg actually decodes the exported bytes.
        """
        mm = img.mm
        total = img.size
        frames: list[RawFrame] = []
        pos = 0
        ps_runs = 0
        annexb_runs = 0
        counter = 0

        try:
            while pos < total:
                m = _CANDIDATE_RE.search(mm, pos)
                if m is None:
                    break
                p = m.start()
                if mm[p + 3] == 0xBA:
                    run = _carve_ps_run(mm, p, total)
                    kind = "ps"
                else:
                    run = _carve_annexb_run(mm, p, total)
                    kind = "annexb"

                if run is None:
                    pos = p + 3
                    continue

                spans, end = run
                for start, stop, ftype, key in spans:
                    frames.append(RawFrame(
                        brand="hikvision", camera=0, sequence=counter, timestamp=None,
                        disk_offset=start, frame_size=stop - start,
                        frame_type=ftype, is_keyframe=key,
                    ))
                    counter += 1
                if kind == "ps":
                    ps_runs += 1
                else:
                    annexb_runs += 1
                pos = max(end, p + 3)

                if progress_cb:
                    try:
                        progress_cb(pos, total)
                    except Exception:
                        pass
        except Exception as exc:
            note = (
                f"Hikvision stream carving stopped early: {exc}. "
                "Results so far are UNCERTAIN — verify on a real disk."
            )
            log.warning(note)
            return frames, note

        note = (
            f"Hikvision stream carving complete: {ps_runs} MPEG-PS run(s) and "
            f"{annexb_runs} H.264 Annex B run(s), {len(frames)} unit(s). Only the "
            "standard stream structure was validated — Hikvision index, channel and "
            "timestamps are NOT parsed. All results are UNCERTAIN until ffprobe "
            "decodes the export. See docs/format_sheets/hikvision.md §4."
        )
        log.info(note)
        return frames, note


# ── Standards-based stream carving helpers ────────────────────────────────────

# A candidate is an MPEG-PS pack start (00 00 01 BA) or an H.264 SPS start code
# (00 00 01 + nal_ref_idc!=0, type 7 => 0x27/0x47/0x67).
_CANDIDATE_RE = re.compile(rb"\x00\x00\x01(?:\xBA|[\x27\x47\x67])")
# Inside an Annex B NAL payload, emulation prevention forbids 00 00 00 / 00 00 01,
# so the first occurrence marks the end of the NAL (trailing zeros / next start code).
_NAL_END_RE = re.compile(rb"\x00\x00[\x00\x01]")
_IDENTICAL_RUN_RE = re.compile(rb"(.)\1{%d}" % (H264_TAIL_IDENTICAL_RUN - 1), re.DOTALL)
_MAX_TRAILING_ZEROS = 64


def _ps_pack_header_len(mm, pos: int, size: int) -> Optional[int]:
    """Length of an MPEG-PS pack header at *pos*, or None if the marker bits are wrong."""
    if pos + 14 > size:
        return None
    b = mm[pos : pos + 14]
    if (b[4] & 0xC4) == 0x44:  # MPEG-2 pack header
        if (b[6] & 0x04) and (b[8] & 0x04) and (b[9] & 0x01) and (b[12] & 0x03) == 0x03:
            n = 14 + (b[13] & 0x07)
            return n if pos + n <= size else None
        return None
    if (b[4] & 0xF1) == 0x21:  # MPEG-1 pack header
        if (b[6] & 1) and (b[8] & 1) and (b[9] & 0x80) and (b[11] & 1):
            return 12
    return None


def _carve_ps_run(mm, start: int, size: int):
    """
    Walk an MPEG-PS run beginning at a pack header. Returns
    ([(start, stop, frame_type, is_keyframe), ...], end) with one span per pack,
    or None if this doesn't look like a real program stream.
    """
    packs: list[tuple[int, int]] = []
    pos = start
    pack_start = None
    elements = 0
    has_video = False

    while pos + 4 <= size and mm[pos : pos + 3] == b"\x00\x00\x01":
        sid = mm[pos + 3]
        if sid == 0xBA:
            n = _ps_pack_header_len(mm, pos, size)
            if n is None:
                break
            if pack_start is not None:
                packs.append((pack_start, pos))
            pack_start = pos
            pos += n
            elements += 1
        elif sid == 0xB9:  # program_end_code
            if pack_start is None:
                break
            pos += 4
            packs.append((pack_start, pos))
            pack_start = None
            break
        elif sid in MPEG_PS_PES_STREAM_IDS:
            if pack_start is None or pos + 6 > size:
                break
            length = (mm[pos + 4] << 8) | mm[pos + 5]
            if length == 0 or pos + 6 + length > size:
                break
            if MPEG_PS_VIDEO_STREAM_ID_MIN <= sid <= MPEG_PS_VIDEO_STREAM_ID_MAX:
                has_video = True
            pos += 6 + length
            elements += 1
        else:
            break

    if pack_start is not None:
        packs.append((pack_start, pos))
    if not has_video or elements < MPEG_PS_MIN_ELEMENTS or not packs:
        return None
    return [(a, b, 0xBA, False) for a, b in packs], pos


def _carve_annexb_run(mm, sps_code_pos: int, size: int):
    """
    Walk an H.264 Annex B run starting at an SPS start code. Returns
    ([(start, stop, nal_type, is_idr), ...], end) with one span per slice NAL
    (each span also covers the SPS/PPS/SEI NALs that precede it, so spans tile
    the run exactly), or None if this isn't a valid SPS -> PPS -> slice opening.
    """
    if sps_code_pos + 5 > size or mm[sps_code_pos + 4] not in H264_VALID_PROFILE_IDC:
        return None

    nals: list[tuple[int, int, int, int]] = []  # (unit_start, end, nal_type, code_pos)
    p = sps_code_pos
    unit_start = p - 1 if p > 0 and mm[p - 1] == 0 else p

    while p + 4 <= size:
        header = mm[p + 3]
        nal_type = header & 0x1F
        if (header & 0x80) or nal_type not in H264_VALID_NAL_TYPES:
            break
        m = _NAL_END_RE.search(mm, p + 4)
        end = m.start() if m is not None else min(size, p + 4 + H264_MAX_TAIL_NAL_BYTES)
        if end <= p + 4:
            break
        if nal_type in (H264_NAL_SPS, H264_NAL_PPS) and end - p > H264_MAX_PARAM_SET_BYTES:
            # Parameter sets are tiny; an oversized one means this "NAL" swallowed
            # junk up to the next start code (e.g. a stray SPS-looking code).
            break
        nals.append((unit_start, end, nal_type, p))

        # Per Annex B a NAL ends at the next 00 00 00 / 00 00 01 (emulation
        # prevention forbids them inside a payload); the next NAL starts there.
        next_p = None
        if m is not None:
            q = end
            zeros = 0
            while q < size and mm[q] == 0 and zeros < _MAX_TRAILING_ZEROS:
                zeros += 1
                q += 1
            if q < size and mm[q] == 1 and zeros >= 2:
                next_p = q - 2
        if next_p is None:
            break
        p = next_p
        unit_start = end

    if len(nals) < 3 or nals[0][2] != H264_NAL_SPS:
        return None
    if H264_NAL_PPS not in (n[2] for n in nals[:3]):
        return None

    spans: list[tuple[int, int, int, bool]] = []
    group_start = nals[0][0]
    last_vcl_code_pos = 0
    for u_start, end, t, code_pos in nals:
        if t in (H264_NAL_SLICE, H264_NAL_IDR):
            spans.append((group_start, end, t, t == H264_NAL_IDR))
            group_start = end
            last_vcl_code_pos = code_pos
    if not spans:
        return None

    # Every NAL end above is exact EXCEPT the run's last slice: Annex B cannot say
    # where it ends when arbitrary filler follows it (the next start code found may
    # be far past real data). Conservative heuristic for that one slice only: a run
    # of >=16 identical bytes is treated as the end of the stream. Real slices can
    # (rarely) contain such runs, so the failure mode is under-recovering the final
    # slice — never absorbing trailing junk into the export.
    s_start, s_end, s_type, s_key = spans[-1]
    tail = _IDENTICAL_RUN_RE.search(mm, last_vcl_code_pos + 4, s_end)
    if tail is not None:
        if tail.start() <= last_vcl_code_pos + 4:
            spans.pop()
            if not spans:
                return None
        else:
            spans[-1] = (s_start, tail.start(), s_type, s_key)
    return spans, spans[-1][1]
