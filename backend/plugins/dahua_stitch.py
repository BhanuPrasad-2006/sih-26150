"""
dahua_stitch.py — put back DHAV frames that straddle interleaved disk clusters.

The problem. On a Dahua disk several cameras record at once, and the recorder hands out clusters to whichever camera
needs one next, so one camera's footage is spread over clusters with other cameras' clusters in between. A frame that
starts near the end of a cluster continues in one of that camera's LATER clusters, not in the bytes that follow on disk.
The plain carver (dahua.py) reads a frame's length from its header and expects the trailer right after that many bytes;
for a straddling frame the trailer is not there (other camera's data is), so the frame is rejected. Keyframes are the
largest frames and straddle most often, and without its keyframe the following frames cannot be decoded: the footage
"looks" recovered but is not.

The fix (the idea of stitching by channel and continuity is from MDPI Information 17(5):493, 2026; the method below
is our own and is only as strong as its checks). For a frame whose header is valid but whose trailer is missing:

  1. The cluster size comes from the DHFS boot sector, which survives deletion of the descriptors. Without it nothing
     is stitched.
  2. From the frame's length we know exactly how many bytes are still missing, hence how many full clusters follow and
     how long the last piece is.
  3. The last cluster is the one that holds the frame's trailer (b"dhav" + the same length) at exactly that position
     AND is followed by the next frame of the SAME camera (frame number within +3). Trailer plus continuation is an
     8-byte exact match plus a valid header: a coincidence is practically impossible.
  4. Any clusters in between must be unambiguous: exactly as many unclaimed, header-less, non-empty clusters as needed
     lie between the start and the last cluster. If there are more candidates than needed, we do NOT guess: the frame stays rejected.

Nothing is ever invented: a frame is only stitched when the bytes it is built from are pinned down by those checks, and
it is reported with the list of disk ranges it was assembled from (the exporter concatenates them in order).
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from backend.models import RawFrame
from backend.plugins.constants import DHAV_TRAILER_MAGIC, DHAV_TRAILER_SIZE

log = logging.getLogger(__name__)

# How far ahead (in clusters) a continuation is searched for. The recorder allocates a camera's clusters in
# increasing order, so the next piece is normally close; a bound keeps the work per frame small on huge disks.
SEARCH_WINDOW_CLUSTERS = 256
# Upper bound on trailer probes in one scan, so a huge, badly damaged disk cannot make the stitching run for hours.
MAX_PROBES = 40_000_000
# Frame numbers of the same camera may skip a little (audio frames, dropped frames): same tolerance as the paper.
SEQUENCE_TOLERANCE = 3


@dataclass(frozen=True)
class OpenFrame:
    """A DHAV header that is valid but whose trailer is not where its length says (a straddling or damaged frame)."""
    pos: int
    channel: int
    sequence: int
    total: int
    timestamp: datetime
    frame_type: int
    is_keyframe: bool


@dataclass
class StitchStats:
    candidates: int = 0
    stitched: int = 0
    ambiguous: int = 0          # more than one possible continuation: left alone on purpose
    unresolved: int = 0         # no continuation found (overwritten, or genuinely damaged)
    skipped_for_time: int = 0   # not attempted: the probe budget ran out


def _looks_empty(mm, start: int, size: int) -> bool:
    """A cluster that is constant at its start, middle and end holds no compressed video (never written or wiped)."""
    probe = 32
    for at in (start, start + max(0, size // 2 - probe // 2), start + max(0, size - probe)):
        chunk = bytes(mm[at:at + probe])
        if len(chunk) < probe or chunk.count(chunk[:1]) != len(chunk):
            return False
    return True


def _cluster_index(part, pos: int) -> Optional[int]:
    if pos < part.video_area:
        return None
    idx = (pos - part.video_area) // part.cluster_size
    return idx if idx < part.desc_count else None


def _find_partition(parts, pos: int):
    for p in parts:
        if _cluster_index(p, pos) is not None:
            return p
    return None


def stitch(
    mm,
    image_size: int,
    parts: list,
    good_frames: list[RawFrame],
    open_frames: list[OpenFrame],
    parse_header: Callable[[object, int, int], Optional[OpenFrame]],
) -> tuple[list[RawFrame], StitchStats]:
    """Return the frames that could be stitched from `open_frames`, and counts of what happened."""
    stats = StitchStats(candidates=len(open_frames))
    stitched: list[RawFrame] = []
    if not parts or not open_frames:
        stats.unresolved = len(open_frames)
        return stitched, stats

    # Which clusters are already spoken for: they hold a frame header (good or open) or a good frame's bytes.
    busy: dict[int, set[int]] = {id(p): set() for p in parts}          # per partition: cluster indexes
    for f in good_frames:
        part = _find_partition(parts, f.disk_offset)
        if part is None:
            continue
        first, last = _cluster_index(part, f.disk_offset), _cluster_index(part, f.disk_offset_end - 1)
        if first is None:
            continue
        busy[id(part)].update(range(first, (last if last is not None else first) + 1))
    for o in open_frames:
        part = _find_partition(parts, o.pos)
        if part is not None:
            busy[id(part)].add(_cluster_index(part, o.pos))

    probes = 0
    for o in sorted(open_frames, key=lambda x: x.pos):
        if probes >= MAX_PROBES:
            stats.skipped_for_time += 1
            continue
        part = _find_partition(parts, o.pos)
        if part is None:
            stats.unresolved += 1
            continue
        cs, va = part.cluster_size, part.video_area
        i = _cluster_index(part, o.pos)
        head_len = va + (i + 1) * cs - o.pos                         # bytes of the frame inside its first cluster
        need = o.total - head_len                                      # bytes still to come from later clusters
        if need <= 0:
            stats.unresolved += 1                                      # fits in its cluster: damaged, not straddling
            continue
        # the frame ends in the m+1'th following cluster; r = bytes of it in that last cluster (must hold the trailer)
        m = max(0, -(-(need - cs) // cs))
        r = need - m * cs
        if r < DHAV_TRAILER_SIZE:
            stats.unresolved += 1
            continue

        trailer = DHAV_TRAILER_MAGIC + struct.pack("<I", o.total)
        finals: list[int] = []
        with_continuity: list[int] = []
        for j in range(i + 1 + m, min(part.desc_count, i + 1 + m + SEARCH_WINDOW_CLUSTERS)):
            start = va + j * cs
            probes += 1
            if start + r > image_size:
                break
            tpos = start + r - DHAV_TRAILER_SIZE
            if bytes(mm[tpos:tpos + DHAV_TRAILER_SIZE]) != trailer:
                continue
            finals.append(j)
            if r < cs:                                                 # a next frame should follow inside this cluster
                nxt = parse_header(mm, start + r, image_size)
                if nxt is not None and nxt.channel == o.channel and 0 < nxt.sequence - o.sequence <= SEQUENCE_TOLERANCE:
                    with_continuity.append(j)
        chosen = with_continuity if with_continuity else finals
        if len(chosen) == 0:
            stats.unresolved += 1
            continue
        if len(chosen) > 1:
            stats.ambiguous += 1
            continue
        j = chosen[0]

        middle: list[int] = []
        if m:
            free = [c for c in range(i + 1, j)
                    if c not in busy[id(part)] and not _looks_empty(mm, va + c * cs, cs)]
            if len(free) != m:
                if len(free) > m:
                    stats.ambiguous += 1          # more candidates than needed: we do not guess
                else:
                    stats.unresolved += 1         # not enough free clusters: part of it was overwritten
                continue
            middle = free

        pieces = [(o.pos, va + (i + 1) * cs)] + [(va + c * cs, va + (c + 1) * cs) for c in middle] + [(va + j * cs, va + j * cs + r)]
        first_start, first_end = pieces[0]
        stitched.append(RawFrame(
            brand="dahua", camera=o.channel, sequence=o.sequence, timestamp=o.timestamp,
            disk_offset=first_start, frame_size=first_end - first_start, frame_type=o.frame_type,
            is_keyframe=o.is_keyframe, extra_ranges=tuple(pieces[1:]),
        ))
        busy[id(part)].update(middle)                                   # never reuse a cluster for a second frame
        busy[id(part)].add(j)
        stats.stitched += 1

    return stitched, stats
