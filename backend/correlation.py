"""
correlation.py — Cross-camera / cross-evidence event correlation.

Groups recovered segments that overlap in time across DIFFERENT camera
channels into correlated event clusters, e.g. "Camera 0 and Camera 2 both
have footage between 14:02:10 and 14:03:40".

This is pure time-window clustering over already-recovered segments:
  - No face/object/content analysis of any kind is performed here.
  - It does not claim the underlying events are related beyond temporal
    proximity — the examiner must independently confirm relevance.
  - Segments should be pre-normalized to a common time reference (see
    timeline.normalize_to_utc) before calling this when correlating across
    evidence items from devices with different clock offsets; correlating
    un-normalized timestamps from different devices can give misleading
    results and is the caller's responsibility to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.models import Segment

# Two segments on different cameras are treated as part of the same
# correlated event if their time windows are within this many seconds of
# each other. Overlapping windows always correlate; this tolerance also
# catches near-misses from clock drift or carving/segmentation imprecision.
DEFAULT_CORRELATION_WINDOW_SECONDS = 5.0


@dataclass
class CorrelatedEvent:
    start_time: datetime
    end_time: datetime
    cameras: list[int] = field(default_factory=list)
    segment_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "cameras": sorted(set(self.cameras)),
            "segment_ids": self.segment_ids,
        }


def correlate_segments(
    segments: list[Segment],
    window_seconds: float = DEFAULT_CORRELATION_WINDOW_SECONDS,
) -> list[CorrelatedEvent]:
    """
    Cluster segments whose [start_time, end_time] windows overlap (allowing a
    window_seconds tolerance) and involve 2 or more distinct camera channels.

    Only segments with both start_time and end_time set are considered.
    This is a simple greedy interval merge (segments sorted by start_time,
    each joining the first open cluster whose window it overlaps) — it is
    deliberately conservative rather than an exhaustive interval-graph
    clustering, which is a reasonable trade-off for this scale of data.

    Returns clusters spanning 2+ distinct cameras only — a single camera's
    own consecutive segments are not "cross-camera" correlation and are
    already visible on that camera's own timeline lane.
    """
    dated = [s for s in segments if s.start_time is not None and s.end_time is not None]
    dated.sort(key=lambda s: s.start_time)

    tolerance = timedelta(seconds=window_seconds)
    events: list[CorrelatedEvent] = []

    for seg in dated:
        placed = False
        for ev in events:
            if seg.start_time <= ev.end_time + tolerance and seg.end_time >= ev.start_time - tolerance:
                ev.start_time = min(ev.start_time, seg.start_time)
                ev.end_time = max(ev.end_time, seg.end_time)
                ev.cameras.append(seg.camera)
                ev.segment_ids.append(seg.segment_id)
                placed = True
                break
        if not placed:
            events.append(CorrelatedEvent(
                start_time=seg.start_time,
                end_time=seg.end_time,
                cameras=[seg.camera],
                segment_ids=[seg.segment_id],
            ))

    return [ev for ev in events if len(set(ev.cameras)) >= 2]
