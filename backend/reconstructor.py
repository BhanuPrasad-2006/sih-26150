"""
reconstructor.py — Groups RawFrames into labelled Segments.

Pipeline (per PRD §2.4 steps 4-5):
  1. group_by_camera():  Split frames by camera channel.
  2. sort_by_time():     Sort each camera's frames by timestamp.
  3. split_on_gaps():    Use the adaptive time-gap formula to start new sessions.
  4. validate():         Apply labelling rules to each session → COMPLETE/PARTIAL/UNCERTAIN.
  5. label_all():        Process all cameras and return a flat list of Segments.

Adaptive gap formula (PRD §5.6.3):
  T_gap = max(T_MIN, min(T_MAX, ALPHA * mu + K * sigma))
  where mu and sigma are computed over the last W inter-frame intervals.

Labelling rules (PRD §4.4):
  COMPLETE  — every frame passes all checks AND ffprobe decodes the export cleanly
              AND (if original is known) hashes match.
              We do not label COMPLETE at reconstruction time; the exporter does this
              after ffprobe validation.
  PARTIAL   — frames found but there are gaps, sequence jumps, or unfinished recording.
  UNCERTAIN — some checks failed; timestamp anomalies; too few frames; or the result
              comes from an experimental carving method (e.g. Hikvision NAL carving).
"""

from __future__ import annotations

import logging
import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from backend.models import DiskOffset, RawFrame, Segment, SegmentStatus
from backend.plugins.constants import (
    DHAV_SEQ_GAP_THRESHOLD,
    GAP_ALPHA,
    GAP_K,
    GAP_T_MAX,
    GAP_T_MIN,
    GAP_WINDOW_W,
)

log = logging.getLogger(__name__)

# Brands recovered by standards-based stream carving (no timestamps available)
_STREAM_CARVED_BRANDS = ("hikvision", "generic")

# Minimum frames for a segment to be PARTIAL instead of UNCERTAIN
_MIN_FRAMES_FOR_PARTIAL = 2


def _group_by_camera_and_stream(frames: list[RawFrame]) -> dict[tuple[int, int], list[RawFrame]]:
    """Partition by (camera, stream_id) so distinct on-disk streams never interleave."""
    groups: dict[tuple[int, int], list[RawFrame]] = defaultdict(list)
    for f in frames:
        groups[(f.camera, f.stream_id)].append(f)
    return dict(groups)


def group_by_camera(frames: list[RawFrame]) -> dict[int, list[RawFrame]]:
    """Partition frames by camera channel. Returns dict camera → [frames]."""
    groups: dict[int, list[RawFrame]] = defaultdict(list)
    for f in frames:
        groups[f.camera].append(f)
    return dict(groups)


def sort_by_time(frames: list[RawFrame]) -> list[RawFrame]:
    """Sort frames by timestamp; frames without timestamps go last."""
    return sorted(frames, key=lambda f: (f.timestamp is None, f.timestamp or datetime.min.replace(tzinfo=timezone.utc)))


def adaptive_gap_threshold(recent_gaps: list[float]) -> float:
    """
    Compute T_gap from the last W inter-frame intervals.
    Falls back to GAP_T_MAX when there is not enough data.
    All defaults are PROPOSED — tune on real data before reporting numbers.
    """
    w = min(len(recent_gaps), GAP_WINDOW_W)
    if w < 2:
        return GAP_T_MAX
    window = recent_gaps[-w:]
    mu = sum(window) / len(window)
    variance = sum((x - mu) ** 2 for x in window) / len(window)
    sigma = math.sqrt(variance)
    t_gap = GAP_ALPHA * mu + GAP_K * sigma
    return max(GAP_T_MIN, min(GAP_T_MAX, t_gap))


def split_on_gaps(frames: list[RawFrame]) -> list[list[RawFrame]]:
    """
    Divide a sorted frame list into sessions.
    A new session starts when:
      - The time gap between consecutive frames exceeds T_gap (adaptive), OR
      - The sequence number jumps by more than DHAV_SEQ_GAP_THRESHOLD, OR
      - A frame has no timestamp (always starts a new session).
    Returns a list of frame-groups (each group = one recording session).
    """
    if not frames:
        return []

    sessions: list[list[RawFrame]] = []
    current: list[RawFrame] = [frames[0]]
    recent_gaps: list[float] = []

    for prev, curr in zip(frames, frames[1:]):
        new_session = False

        # Timestamp-based gap
        if prev.timestamp is None or curr.timestamp is None:
            # Stream-carved Hikvision units carry no timestamps; they belong to the
            # same recording exactly when they are byte-contiguous on disk.
            contiguous_stream = (
                prev.brand in _STREAM_CARVED_BRANDS
                and curr.brand == prev.brand
                and prev.disk_offset_end == curr.disk_offset
            )
            new_session = not contiguous_stream
        else:
            gap_s = (curr.timestamp - prev.timestamp).total_seconds()
            if gap_s < 0:
                # Non-monotone time → new session
                new_session = True
            else:
                t_gap = adaptive_gap_threshold(recent_gaps)
                if gap_s > t_gap:
                    new_session = True
                else:
                    recent_gaps.append(gap_s)

        # Sequence number gap (Dahua only; sequence is 0 for Hikvision carving)
        if (
            not new_session
            and prev.brand == "dahua"
            and curr.brand == "dahua"
            and prev.sequence != 0
            and curr.sequence != 0
        ):
            seq_jump = curr.sequence - prev.sequence
            if seq_jump < 0 or seq_jump > DHAV_SEQ_GAP_THRESHOLD:
                new_session = True

        if new_session:
            sessions.append(current)
            current = [curr]
            recent_gaps = []
        else:
            current.append(curr)

    sessions.append(current)
    return sessions


def _label_session(session: list[RawFrame], evidence_id: str) -> Segment:
    """
    Build a Segment from one session of frames and assign a status label.
    """
    brand = session[0].brand

    # Collect contiguous disk offset ranges
    offsets: list[DiskOffset] = []
    for frame in session:
        if frame.frame_size > 4:  # ignore placeholder entries
            # Coalesce byte-contiguous ranges: identical export bytes, far fewer rows.
            if offsets and offsets[-1].end == frame.disk_offset:
                offsets[-1] = DiskOffset(start=offsets[-1].start, end=frame.disk_offset_end)
            else:
                offsets.append(DiskOffset(start=frame.disk_offset, end=frame.disk_offset_end))

    # Timestamps
    timestamps = [f.timestamp for f in session if f.timestamp is not None]
    start_time = min(timestamps) if timestamps else None
    end_time   = max(timestamps) if timestamps else None

    # Status heuristics
    has_gaps = len(session) < 2
    any_no_timestamp = any(f.timestamp is None for f in session)
    # Carving methods whose output has not been verified against real hardware.
    from_experimental_brand = brand in ("hikvision", "generic", "cpplus", "honeywell")

    if from_experimental_brand:
        # Experimental carving is always UNCERTAIN until independently verified.
        status = SegmentStatus.UNCERTAIN
        if brand == "hikvision":
            notes = (
                "Hikvision stream carving: a contiguous MPEG-PS / H.264 Annex B "
                "stream was located and its standard structure validated. Hikvision's "
                "own index, channel and timestamps are NOT parsed (unverified), so no "
                "time range or true camera number is available. UNCERTAIN until "
                "export and ffprobe confirm the bytes decode (then PARTIAL). "
                "See docs/format_sheets/hikvision.md §4."
            )
        elif brand == "generic":
            notes = (
                "Generic stream carving (brand not identified): a contiguous MPEG-PS / "
                "H.264 Annex B stream was located and its standard structure validated. "
                "No recorder-specific layout was used, so no timestamps or camera number "
                "are available. UNCERTAIN until export and ffprobe confirm the bytes "
                "decode (then PARTIAL)."
            )
        elif brand == "honeywell":
            notes = (
                "Honeywell record carving (layout from Yoon & Hwang, arXiv:2605.07430, one "
                "device model): 20-byte record headers and H.264 payloads were located; "
                "timestamps come from the record headers. The camera channel is not "
                "recoverable without the Video Channel List, so each on-disk stream is "
                "reported separately as camera 0. Not validated on real Honeywell "
                "hardware: UNCERTAIN until export and ffprobe confirm the bytes decode "
                "(then PARTIAL)."
            )
        else:
            notes = (
                "CP Plus (Dahua-compatible detection — unverified). Carved via "
                "the Dahua DHAV engine, but native CP Plus support has not been "
                "verified against real CP Plus hardware. UNCERTAIN until "
                "independently confirmed."
            )
    elif any_no_timestamp or has_gaps:
        status = SegmentStatus.UNCERTAIN
        notes = "Some frames missing timestamps or too few frames to confirm integrity."
    elif len(session) < _MIN_FRAMES_FOR_PARTIAL:
        status = SegmentStatus.UNCERTAIN
        notes = f"Only {len(session)} frame(s) found — too few to be reliable."
    else:
        # Default for Dahua carving: PARTIAL (upgraded to COMPLETE by exporter after ffprobe)
        status = SegmentStatus.PARTIAL
        notes = "Carved frames — awaiting ffprobe validation before COMPLETE label."

    return Segment(
        segment_id=str(uuid.uuid4()),
        evidence_id=evidence_id,
        camera=session[0].camera,
        start_time=start_time,
        end_time=end_time,
        disk_offsets=offsets,
        frame_count=len(session),
        status=status,
        notes=notes,
    )


def label_all(
    frames: list[RawFrame],
    evidence_id: str,
) -> list[Segment]:
    """
    Full reconstruction pipeline: group → sort → split → label.
    Returns a flat list of Segments ready for DB storage.
    """
    if not frames:
        return []

    by_camera = _group_by_camera_and_stream(frames)
    segments: list[Segment] = []

    for (camera_id, _stream_id), cam_frames in sorted(by_camera.items()):
        sorted_frames = sort_by_time(cam_frames)
        sessions = split_on_gaps(sorted_frames)
        for session in sessions:
            if session:
                seg = _label_session(session, evidence_id)
                segments.append(seg)
                log.debug(
                    "Camera %d: session %s frames=%d status=%s",
                    camera_id, seg.segment_id[:8], seg.frame_count, seg.status,
                )

    log.info(
        "Reconstruction complete: %d cameras, %d segments total.",
        len(by_camera), len(segments),
    )
    return segments


def reconstruct_segments(frames: list[RawFrame], ev_id: str | int, brand: str = "Dahua") -> list[Segment]:
    """Convenience alias for label_all."""
    return label_all(frames, str(ev_id))

