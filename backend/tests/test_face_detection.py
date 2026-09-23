"""
test_face_detection.py — Unit and integration tests for AI-Based Face Detection.

Verifies:
  1. Model file is present and loadable (cv2.FaceDetectorYN).
  2. A video with no faces (synthetic, non-face content) is NOT flagged.
  3. Video files are treated strictly read-only (evidence integrity preserved).
  4. Labeled "AI-Based Face Detection", distinct from motion.py's classical method.
  5. Missing file / missing model are handled gracefully, never raise.
  6. API endpoint POST /api/cases/{case_id}/face-detect/{segment_id} works as a
     decoupled post-export step, mirroring the motion-detection endpoint.

Note: this suite intentionally does NOT include a real photograph of a person
as a fixture (consistent with this project's synthetic-data-only testing
convention — see motion.py's create_synthetic_test_video). It therefore
verifies the negative case (no false positives on non-face synthetic video)
and the plumbing end-to-end, but does not assert a positive detection on a
real face — that would require a real sample the project deliberately does
not commit to test fixtures.
"""

import hashlib
from pathlib import Path

from backend.face_detection import (
    FACE_DETECTION_LABEL,
    detect_faces_in_video,
    model_available,
)
from backend.models import Segment, SegmentStatus
from backend.motion import create_synthetic_test_video


def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_face_detection_model_is_available():
    """The YuNet ONNX model must be present for face detection to function."""
    assert model_available() is True


def test_face_detection_synthetic_nonface_clip_not_detected(tmp_path):
    """A synthetic clip with no face content must not be flagged (no false positive)."""
    video_path = tmp_path / "nonface_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=30)

    result = detect_faces_in_video(actual_path)

    assert result.error is None
    assert result.faces_detected is False
    assert result.frames_with_faces == 0
    assert result.frames_sampled > 0
    assert result.label == FACE_DETECTION_LABEL
    assert "AI-Based" in result.label
    assert "no faces detected" in result.summary.lower()


def test_face_detection_evidence_integrity_unaltered(tmp_path):
    """Face detection must read the exported video read-only, leaving its hash unchanged."""
    video_path = tmp_path / "integrity_test_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=20)

    hash_before = hash_file(actual_path)
    result = detect_faces_in_video(actual_path)
    hash_after = hash_file(actual_path)

    assert hash_before == hash_after
    assert result.error is None


def test_face_detection_nonexistent_file(tmp_path):
    """Missing video file handles gracefully without raising uncaught exceptions."""
    missing = tmp_path / "nonexistent.mp4"
    result = detect_faces_in_video(missing)
    assert result.faces_detected is False
    assert result.error is not None
    assert "file not found" in result.summary.lower()


def test_face_detection_frame_stride_reduces_sampled_frames(tmp_path):
    """A larger frame_stride should sample fewer frames than analyzing every frame."""
    video_path = tmp_path / "stride_clip.mp4"
    actual_path = create_synthetic_test_video(video_path, has_motion=True, num_frames=30)

    dense = detect_faces_in_video(actual_path, frame_stride=1)
    sparse = detect_faces_in_video(actual_path, frame_stride=10)

    assert dense.frames_sampled > sparse.frames_sampled


def test_face_detection_api_endpoint(auth_client, tmp_path):
    """
    Test POST /api/cases/{case_id}/face-detect/{segment_id} as a decoupled
    post-export endpoint, mirroring the motion-detection endpoint contract.
    """
    res = auth_client.post("/api/cases", json={"case_number": "FACE-TEST-001", "examiner": "Det. Sharma"})
    assert res.status_code == 200
    case_id = res.json()["case_id"]

    fake_img = tmp_path / "evid.dd"
    fake_img.write_bytes(b"\x00" * 4096)
    res = auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": str(fake_img), "label": "EVID-1"})
    assert res.status_code == 200
    evidence_id = res.json()["evidence_id"]

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

    face_res = auth_client.post(f"/api/cases/{case_id}/face-detect/{seg.segment_id}")
    assert face_res.status_code == 200
    data = face_res.json()

    assert data["segment_id"] == seg.segment_id
    assert data["faces_detected"] is False  # synthetic non-face clip
    assert data["label"] == FACE_DETECTION_LABEL

    updated_segs = db.list_segments_for_evidence(evidence_id)
    assert len(updated_segs) == 1
    assert updated_segs[0].face_detected is False
    assert FACE_DETECTION_LABEL in updated_segs[0].face_detection_details

    unexported_seg = Segment(
        evidence_id=evidence_id,
        camera=1,
        frame_count=10,
        status=SegmentStatus.UNCERTAIN,
    )
    db.save_segment(unexported_seg)

    bad_res = auth_client.post(f"/api/cases/{case_id}/face-detect/{unexported_seg.segment_id}")
    assert bad_res.status_code == 400
    assert "has not been exported yet" in bad_res.json()["detail"].lower()
