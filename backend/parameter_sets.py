"""
parameter_sets.py — H.264 parameter sets (SPS/PPS) for footage that lost its own.

An H.264 picture cannot be decoded without the stream's parameter sets: small blocks of settings (frame size, profile,
entropy coding...) that recorders write in front of keyframes. If deletion or overwriting destroyed the copy in front of
the first keyframe of a recovered piece, that piece will not play even though its picture data is intact.

The recorder writes the SAME settings for every recording of a camera, so the copy from another piece of the same
camera can be put back in front. This is the simple cousin of Altinisik & Sencar (IEEE TIFS 2021, arXiv 2104.14522),
who GENERATE missing headers by trial for fragments with no other source; we only BORROW existing ones, and we say so
in the segment's notes. Parameter sets are settings, not picture content: nothing about what the video shows is added.

Limits: it can only help a piece that begins at a keyframe. Frames that depend on a keyframe that is gone cannot be
decoded by anyone, and pieces starting mid-picture-group are left exactly as they are.
"""

from __future__ import annotations

import struct
from typing import Iterable, Optional

from backend.plugins.constants import (
    DHAV_MIN_HEADER_SIZE,
    DHAV_OFF_EXT_LENGTH,
    DHAV_OFF_FRAME_TYPE,
    DHAV_OFF_TOTAL_SIZE,
    DHAV_TRAILER_SIZE,
    DHAV_TYPE_VIDEO_DELTA,
    DHAV_TYPE_VIDEO_KEYFRAME,
)

NAL_IDR, NAL_SPS, NAL_PPS = 5, 7, 8
START = b"\x00\x00\x00\x01"


def dhav_video_payloads(raw: bytes) -> Iterable[bytes]:
    """The H.264 payload of every video frame in a raw DHAV byte string (audio and unknown frames are skipped)."""
    pos, n = 0, len(raw)
    while pos + DHAV_MIN_HEADER_SIZE <= n:
        if raw[pos:pos + 4] != b"DHAV":
            pos += 1
            continue
        total = struct.unpack_from("<I", raw, pos + DHAV_OFF_TOTAL_SIZE)[0]
        ext = raw[pos + DHAV_OFF_EXT_LENGTH]
        start, end = pos + DHAV_MIN_HEADER_SIZE + ext, pos + total - DHAV_TRAILER_SIZE
        if total < DHAV_MIN_HEADER_SIZE + ext + DHAV_TRAILER_SIZE or pos + total > n or start > end:
            pos += 4
            continue
        if raw[pos + DHAV_OFF_FRAME_TYPE] in (DHAV_TYPE_VIDEO_DELTA, DHAV_TYPE_VIDEO_KEYFRAME):
            yield raw[start:end]
        pos += total


def split_nals(annexb: bytes) -> list[bytes]:
    """NAL units (start code included) of an Annex B byte string."""
    marks = []
    i = annexb.find(b"\x00\x00\x01")
    while i != -1:
        marks.append(i - 1 if i > 0 and annexb[i - 1] == 0 else i)
        i = annexb.find(b"\x00\x00\x01", i + 3)
    marks.append(len(annexb))
    return [annexb[a:b] for a, b in zip(marks, marks[1:]) if b > a]


def nal_type(nal: bytes) -> int:
    i = nal.find(b"\x01") + 1
    return nal[i] & 0x1F if 0 < i < len(nal) else -1


def find_sps_pps(annexb: bytes) -> Optional[tuple[bytes, bytes]]:
    """The first (SPS, PPS) pair in the stream, each normalised to a 4-byte start code, or None."""
    sps = pps = None
    for nal in split_nals(annexb):
        t = nal_type(nal)
        body = nal[nal.find(b"\x01") + 1:]
        if t == NAL_SPS and sps is None:
            sps = START + body
        elif t == NAL_PPS and pps is None:
            pps = START + body
        if sps and pps:
            return sps, pps
    return None


def first_idr_lacks_parameter_sets(annexb: bytes) -> bool:
    """True when a keyframe (IDR) is present but no SPS and PPS come before it."""
    seen_sps = seen_pps = False
    for nal in split_nals(annexb):
        t = nal_type(nal)
        if t == NAL_SPS:
            seen_sps = True
        elif t == NAL_PPS:
            seen_pps = True
        elif t == NAL_IDR:
            return not (seen_sps and seen_pps)
    return False


def drop_before_first_idr(annexb: bytes) -> bytes:
    """Frames before the first keyframe cannot be decoded (they depend on a picture that is gone): start at the IDR,
    keeping any parameter sets that sit directly in front of it."""
    nals = split_nals(annexb)
    for k, nal in enumerate(nals):
        if nal_type(nal) == NAL_IDR:
            j = k
            while j > 0 and nal_type(nals[j - 1]) in (NAL_SPS, NAL_PPS, 6):     # 6 = SEI
                j -= 1
            return b"".join(nals[j:])
    return annexb


def repair_stream(raw_dhav: bytes, donor: tuple[bytes, bytes]) -> Optional[bytes]:
    """
    An Annex B elementary stream for a DHAV piece whose keyframe lost its parameter sets: the piece's video payloads,
    starting at its first keyframe, with the donor SPS+PPS put in front. None when the piece has no keyframe or
    already carries its own parameter sets (then there is nothing to repair).
    """
    stream = b"".join(dhav_video_payloads(raw_dhav))
    if not first_idr_lacks_parameter_sets(stream):
        return None
    trimmed = drop_before_first_idr(stream)
    if not trimmed or nal_type(split_nals(trimmed)[0]) not in (NAL_IDR, 6):
        return None
    return donor[0] + donor[1] + trimmed
