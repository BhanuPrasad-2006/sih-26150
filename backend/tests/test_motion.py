"""
test_motion.py — Unit and integration tests for Basic Motion Detection.

Verifies:
  1. A video clip with motion is flagged as motion detected.
  2. A static video clip with no motion is NOT flagged.
  3. Video files are treated strictly read-only (evidence integrity preserved).
  4. Labeled strictly as "Basic Motion Detection", never "AI Analytics".
  5. API endpoint POST /api/cases/{case_id}/motion/{segment_id} works as a decoupled post-export step.
"""

import hashlib
from pathlib import Path

import pytest

from backend.models import Case, Evidence, Segment, SegmentStatus
from backend.motion import (
    MOTION_LABEL,
    create_synthetic_test_video,
    detect_motion_in_video,
)


def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_motion_clip_with_movement_detected(tmp_path):
    """A clip with moving objects must be flagged as motion detected."""
    video_path = tmp_path / "motion_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=30)

    result = detect_motion_in_video(actual_path)

    assert result.motion_detected is True
    assert result.motion_frames > 0
    assert result.total_frames >= 25
    assert result.label == "Basic Motion Detection"
    assert "AI" not in result.label
    assert "motion detected" in result.summary.lower()


def test_motion_static_clip_not_detected(tmp_path):
    """A static clip with no movement must NOT be flagged as motion detected."""
    video_path = tmp_path / "static_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=False, num_frames=30)

    result = detect_motion_in_video(actual_path)

    assert result.motion_detected is False
    assert result.motion_frames == 0
    assert result.label == "Basic Motion Detection"
    assert "no significant motion" in result.summary.lower()


def test_motion_evidence_integrity_unaltered(tmp_path):
    """Motion detection must read the exported video in read-only mode, leaving hash unchanged."""
    video_path = tmp_path / "integrity_test_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=20)

    hash_before = hash_file(actual_path)
    result = detect_motion_in_video(actual_path)
    hash_after = hash_file(actual_path)

    assert hash_before == hash_after
    assert result.motion_detected is True


def test_motion_nonexistent_file(tmp_path):
    """Missing video file handles gracefully without raising uncaught exceptions."""
    missing = tmp_path / "nonexistent.mp4"
    result = detect_motion_in_video(missing)
    assert result.motion_detected is False
    assert result.error is not None
    assert "file not found" in result.summary.lower()


def test_motion_api_endpoint(auth_client, tmp_path):
    """
    Test POST /api/cases/{case_id}/motion/{segment_id} as a decoupled post-export endpoint.
    """
    # 1. Create a case
    res = auth_client.post("/api/cases", json={"case_number": "MOTION-TEST-001", "examiner": "Det. Sharma"})
    assert res.status_code == 200
    case_id = res.json()["case_id"]

    # 2. Add evidence image file
    fake_img = tmp_path / "evid.dd"
    fake_img.write_bytes(b"\x00" * 4096)
    res = auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": str(fake_img), "label": "EVID-1"})
    assert res.status_code == 200
    evidence_id = res.json()["evidence_id"]

    # 3. Create synthetic test video and insert segment into DB
    video_path = tmp_path / "exported_seg.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=25)

    import backend.main as main_mod
    db = main_mod.db

    seg = Segment(
        evidence_id=evidence_id,
        camera=0,
        frame_count=25,
        status=SegmentStatus.PARTIAL,
        export_path=str(actual_path),
        sha256=hash_file(actual_path),
    )
    db.save_segment(seg)

    # 4. Call motion endpoint
    motion_res = auth_client.post(f"/api/cases/{case_id}/motion/{seg.segment_id}")
    assert motion_res.status_code == 200
    data = motion_res.json()

    assert data["segment_id"] == seg.segment_id
    assert data["motion_detected"] is True
    assert data["label"] == "Basic Motion Detection"
    assert data["motion_frames"] > 0

    # 5. Verify segment record in DB was updated with motion details
    updated_segs = db.list_segments_for_evidence(evidence_id)
    assert len(updated_segs) == 1
    assert updated_segs[0].motion_detected is True
    assert "Basic Motion Detection" in updated_segs[0].motion_details

    # 6. Test that calling motion on an unexported segment returns 400
    unexported_seg = Segment(
        evidence_id=evidence_id,
        camera=1,
        frame_count=10,
        status=SegmentStatus.UNCERTAIN,
    )
    db.save_segment(unexported_seg)

    bad_res = auth_client.post(f"/api/cases/{case_id}/motion/{unexported_seg.segment_id}")
    assert bad_res.status_code == 400
    assert "has not been exported yet" in bad_res.json()["detail"].lower()
