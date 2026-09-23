"""Pure timeline grouping and per-channel gap detection for recovered segments."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from backend.models import Segment


class TimelineGap(BaseModel):
    """A period with no recovered footage between two segments on one channel."""

    camera: int
    start_time: datetime
    end_time: datetime
    duration_seconds: float


class TimelineLane(BaseModel):
    """Timeline data for one camera/channel."""

    camera: int
    segments: list[Segment] = Field(default_factory=list)
    gaps: list[TimelineGap] = Field(default_factory=list)


class TimelineData(BaseModel):
    """Serializable shared-timeline view for every recovered segment in a case."""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    lanes: list[TimelineLane] = Field(default_factory=list)
    unplaced_segments: list[Segment] = Field(default_factory=list)


def _as_utc(timestamp: Optional[datetime]) -> Optional[datetime]:
    """Normalize timestamps for safe ordering while preserving UTC in API output."""
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def normalize_to_utc(
    timestamp: Optional[datetime],
    device_utc_offset_minutes: Optional[int],
) -> Optional[datetime]:
    """
    Convert a device-reported timestamp to normalized UTC using an
    examiner-supplied device clock offset.

    Carved timestamps are parsed as raw device-reported values (the DHAV
    format sheet marks the true epoch/timezone as TO VERIFY) — this project
    never infers a device's timezone automatically. When the examiner has
    confirmed the offset for a given piece of evidence (Evidence.
    device_utc_offset_minutes), subtracting it here yields a true UTC instant
    that is comparable across evidence items from devices in different
    timezones, e.g. for cross-camera/cross-device correlation.

    Returns the timestamp UNCHANGED (still device-reported, not normalized)
    when no offset has been supplied — this function never guesses.
    """
    if timestamp is None or device_utc_offset_minutes is None:
        return timestamp
    ts = _as_utc(timestamp)
    if ts is None:
        return None
    return ts - timedelta(minutes=device_utc_offset_minutes)


def _normalised_segment(segment: Segment) -> Optional[Segment]:
    """Return a timestamp-normalized segment or ``None`` when it cannot be placed."""
    start_time = _as_utc(segment.start_time)
    end_time = _as_utc(segment.end_time)
    if start_time is None or end_time is None or end_time < start_time:
        return None
    return segment.model_copy(update={"start_time": start_time, "end_time": end_time})


def _gaps_for_lane(camera: int, segments: list[Segment]) -> list[TimelineGap]:
    """Find uncovered intervals, accounting for overlapping recovered segments."""
    if len(segments) < 2:
        return []

    gaps: list[TimelineGap] = []
    covered_until = segments[0].end_time
    assert covered_until is not None  # guaranteed by _normalised_segment

    for segment in segments[1:]:
        start_time = segment.start_time
        end_time = segment.end_time
        assert start_time is not None and end_time is not None

        if start_time > covered_until:
            gaps.append(TimelineGap(
                camera=camera,
                start_time=covered_until,
                end_time=start_time,
                duration_seconds=(start_time - covered_until).total_seconds(),
            ))
        if end_time > covered_until:
            covered_until = end_time

    return gaps


def build_timeline(segments: Iterable[Segment]) -> TimelineData:
    """
    Group recoverable segments by camera, order them by UTC timestamp, and find
    gaps between non-overlapping coverage windows on each camera.

    Segments that lack a valid start/end interval remain visible to callers in
    ``unplaced_segments`` rather than being silently omitted from the case.
    """
    by_camera: dict[int, list[Segment]] = defaultdict(list)
    unplaced_segments: list[Segment] = []

    for segment in segments:
        normalised = _normalised_segment(segment)
        if normalised is None:
            unplaced_segments.append(segment)
        else:
            by_camera[normalised.camera].append(normalised)

    lanes: list[TimelineLane] = []
    placed_segments: list[Segment] = []
    for camera in sorted(by_camera):
        lane_segments = sorted(
            by_camera[camera],
            key=lambda segment: (segment.start_time, segment.end_time, segment.segment_id),
        )
        lanes.append(TimelineLane(
            camera=camera,
            segments=lane_segments,
            gaps=_gaps_for_lane(camera, lane_segments),
        ))
        placed_segments.extend(lane_segments)

    if not placed_segments:
        return TimelineData(unplaced_segments=unplaced_segments)

    start_time = min(segment.start_time for segment in placed_segments)
    end_time = max(segment.end_time for segment in placed_segments)
    assert start_time is not None and end_time is not None
    return TimelineData(
        start_time=start_time,
        end_time=end_time,
        duration_seconds=(end_time - start_time).total_seconds(),
        lanes=lanes,
        unplaced_segments=unplaced_segments,
    )
