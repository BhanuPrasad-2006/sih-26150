"""
test_correlation.py — Tests for cross-camera event correlation and
device-clock timestamp normalization.
"""

from datetime import datetime, timedelta, timezone

from backend.correlation import correlate_segments
from backend.models import Segment, SegmentStatus
from backend.timeline import normalize_to_utc


def _seg(camera: int, start: datetime, end: datetime) -> Segment:
    return Segment(
        evidence_id="ev-1",
        camera=camera,
        start_time=start,
        end_time=end,
        status=SegmentStatus.PARTIAL,
    )


def test_correlate_segments_groups_overlapping_different_cameras():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    seg_a = _seg(0, t0, t0 + timedelta(seconds=30))
    seg_b = _seg(1, t0 + timedelta(seconds=10), t0 + timedelta(seconds=40))

    events = correlate_segments([seg_a, seg_b])

    assert len(events) == 1
    assert set(events[0].cameras) == {0, 1}
    assert set(events[0].segment_ids) == {seg_a.segment_id, seg_b.segment_id}


def test_correlate_segments_excludes_single_camera_clusters():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Two overlapping segments, but both on the same camera — not cross-camera.
    seg_a = _seg(0, t0, t0 + timedelta(seconds=30))
    seg_b = _seg(0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=40))

    events = correlate_segments([seg_a, seg_b])

    assert events == []


def test_correlate_segments_respects_window_tolerance():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    seg_a = _seg(0, t0, t0 + timedelta(seconds=10))
    # Starts 100s after seg_a ends — far outside any reasonable tolerance.
    seg_b = _seg(1, t0 + timedelta(seconds=110), t0 + timedelta(seconds=120))

    events = correlate_segments([seg_a, seg_b], window_seconds=5.0)

    assert events == []  # too far apart to correlate


def test_correlate_segments_ignores_segments_without_timestamps():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    seg_a = _seg(0, t0, t0 + timedelta(seconds=30))
    seg_b = Segment(evidence_id="ev-1", camera=1, status=SegmentStatus.UNCERTAIN)  # no timestamps

    events = correlate_segments([seg_a, seg_b])

    assert events == []  # seg_b can't be placed, so no cross-camera cluster forms


def test_normalize_to_utc_passthrough_when_offset_unset():
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert normalize_to_utc(ts, None) == ts
    assert normalize_to_utc(None, 330) is None


def test_normalize_to_utc_subtracts_device_offset():
    # A device configured for IST (UTC+5:30) reports 17:30 local; the true
    # UTC instant is 12:00.
    device_reported = datetime(2026, 1, 1, 17, 30, 0, tzinfo=timezone.utc)
    normalized = normalize_to_utc(device_reported, 330)
    assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_to_utc_handles_naive_timestamps():
    device_reported = datetime(2026, 1, 1, 17, 30, 0)  # naive, assumed UTC-labelled
    normalized = normalize_to_utc(device_reported, 330)
    assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
