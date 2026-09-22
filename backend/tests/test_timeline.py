"""Unit tests for timeline grouping and gap detection, independent of UI rendering."""

from datetime import datetime, timedelta, timezone

from backend.models import Segment, SegmentStatus
from backend.timeline import build_timeline


BASE_TIME = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def _segment(
    segment_id: str,
    camera: int,
    start_minutes: int | None,
    end_minutes: int | None,
    status: SegmentStatus = SegmentStatus.COMPLETE,
) -> Segment:
    return Segment(
        segment_id=segment_id,
        evidence_id="evidence-1",
        camera=camera,
        start_time=BASE_TIME + timedelta(minutes=start_minutes) if start_minutes is not None else None,
        end_time=BASE_TIME + timedelta(minutes=end_minutes) if end_minutes is not None else None,
        frame_count=30,
        status=status,
    )


def test_build_timeline_groups_and_sorts_segments_by_camera():
    timeline = build_timeline([
        _segment("camera-2-later", 2, 30, 35, SegmentStatus.UNCERTAIN),
        _segment("camera-1-later", 1, 20, 25, SegmentStatus.PARTIAL),
        _segment("camera-1-earlier", 1, 0, 10),
        _segment("camera-2-earlier", 2, 5, 15),
    ])

    assert [lane.camera for lane in timeline.lanes] == [1, 2]
    assert [segment.segment_id for segment in timeline.lanes[0].segments] == [
        "camera-1-earlier", "camera-1-later",
    ]
    assert [segment.segment_id for segment in timeline.lanes[1].segments] == [
        "camera-2-earlier", "camera-2-later",
    ]
    assert timeline.start_time == BASE_TIME
    assert timeline.end_time == BASE_TIME + timedelta(minutes=35)
    assert timeline.duration_seconds == 35 * 60


def test_build_timeline_marks_gaps_per_channel_only():
    timeline = build_timeline([
        _segment("camera-1-first", 1, 0, 10),
        _segment("camera-1-second", 1, 25, 30),
        _segment("camera-2-continuous", 2, 12, 28),
    ])

    camera_one = timeline.lanes[0]
    camera_two = timeline.lanes[1]
    assert len(camera_one.gaps) == 1
    gap = camera_one.gaps[0]
    assert gap.camera == 1
    assert gap.start_time == BASE_TIME + timedelta(minutes=10)
    assert gap.end_time == BASE_TIME + timedelta(minutes=25)
    assert gap.duration_seconds == 15 * 60
    assert camera_two.gaps == []


def test_build_timeline_does_not_create_false_gap_for_overlapping_segments():
    timeline = build_timeline([
        _segment("first", 4, 0, 10),
        _segment("overlap", 4, 5, 20),
        _segment("after-overlap", 4, 25, 30),
    ])

    assert len(timeline.lanes[0].gaps) == 1
    gap = timeline.lanes[0].gaps[0]
    assert gap.start_time == BASE_TIME + timedelta(minutes=20)
    assert gap.end_time == BASE_TIME + timedelta(minutes=25)


def test_build_timeline_retains_unplaceable_segments_separately():
    missing_end = _segment("missing-end", 1, 0, None)
    reversed_range = _segment("reversed", 2, 20, 10)

    timeline = build_timeline([_segment("valid", 3, 5, 10), missing_end, reversed_range])

    assert [segment.segment_id for segment in timeline.unplaced_segments] == [
        "missing-end", "reversed",
    ]
    assert [lane.camera for lane in timeline.lanes] == [3]
