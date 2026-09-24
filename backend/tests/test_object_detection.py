"""Tests for backend/object_detection.py (decode maths verified without a model file)."""

import math
from pathlib import Path

import numpy as np
import pytest

from backend import object_detection as od
from backend.models import Segment, SegmentStatus
from backend.motion import create_synthetic_test_video


def _blank_output() -> np.ndarray:
    out = np.zeros((1, 8400, 85), dtype=np.float32)
    out[..., 4] = 0.01                                    # low objectness everywhere
    return out


def _cell_index(gx: int, gy: int, stride: int = 8) -> int:
    """Row of the flattened prediction tensor for a stride-8 grid cell."""
    return gy * (640 // stride) + gx


def test_decode_known_box_and_class():
    out = _blank_output()
    i = _cell_index(10, 20)                               # stride 8, cell (10, 20)
    out[0, i, 0:2] = 0.5                                  # centre offset within the cell
    out[0, i, 2:4] = math.log(80 / 8), math.log(160 / 8)  # 80 x 160 px in network space
    out[0, i, 4] = 0.9
    out[0, i, 5 + 0] = 0.9                                # class 0 = person

    dets = od.decode_yolox(out, ratio=0.5)
    assert len(dets) == 1
    cid, score, (x1, y1, x2, y2) = dets[0]
    assert od.COCO_CLASSES[cid] == "person"
    assert score == pytest.approx(0.81, abs=1e-4)
    cx, cy = (10 + 0.5) * 8, (20 + 0.5) * 8               # network-space centre
    assert (x1, y1, x2, y2) == pytest.approx(
        ((cx - 40) / 0.5, (cy - 80) / 0.5, (cx + 40) / 0.5, (cy + 80) / 0.5), abs=1e-3)


def test_decode_suppresses_duplicate_boxes_and_keeps_distinct_classes():
    out = _blank_output()
    for gx in (10, 11):                                   # two neighbouring cells, near-identical box
        i = _cell_index(gx, 20)
        out[0, i, 0:2] = 0.5 - (gx - 10)                  # keeps the same absolute centre
        out[0, i, 2:4] = math.log(10), math.log(20)
        out[0, i, 4] = 0.9
        out[0, i, 5 + 2] = 0.9 if gx == 10 else 0.8       # class 2 = car
    j = _cell_index(40, 40)                               # unrelated dog elsewhere
    out[0, j, 0:2] = 0.5
    out[0, j, 2:4] = math.log(5), math.log(5)
    out[0, j, 4] = 0.9
    out[0, j, 5 + 16] = 0.9

    dets = od.decode_yolox(out, ratio=1.0)
    names = sorted(od.COCO_CLASSES[c] for c, _, _ in dets)
    assert names == ["car", "dog"]


def test_decode_below_threshold_and_bad_shape():
    assert od.decode_yolox(_blank_output(), ratio=1.0) == []
    with pytest.raises(ValueError):
        od.decode_yolox(np.zeros((1, 100, 85), dtype=np.float32), ratio=1.0)


def test_letterbox_geometry():
    frame = np.full((720, 1280, 3), 200, dtype=np.uint8)
    canvas, ratio = od.letterbox(frame)
    assert canvas.shape == (640, 640, 3) and ratio == pytest.approx(0.5)
    assert canvas[100, 100, 0] == 200 and canvas[600, 100, 0] == 114     # padded below the picture


def test_coco_has_80_classes():
    assert len(od.COCO_CLASSES) == 80 and od.COCO_CLASSES[0] == "person"


def test_hog_engine_used_without_model_and_labelled(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_MODEL_PATH", str(tmp_path / "absent.onnx"))
    assert od.model_available() is False
    video = create_synthetic_test_video(tmp_path / "clip.mp4", has_motion=False, num_frames=12)
    res = od.detect_objects_in_video(video)
    assert res.error is None and res.engine == "hog"
    assert "classical" in res.label and "persons only" in res.label
    assert res.objects_detected is False and res.frames_sampled >= 2
    assert "does not prove" in res.summary.lower()


def test_yolox_requested_but_model_missing_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_MODEL_PATH", str(tmp_path / "absent.onnx"))
    video = create_synthetic_test_video(tmp_path / "clip.mp4", has_motion=False, num_frames=6)
    res = od.detect_objects_in_video(video, force_engine="yolox")
    assert res.error and "model" in res.error.lower()


def test_missing_video_file():
    res = od.detect_objects_in_video("does_not_exist.mp4")
    assert res.error and not res.objects_detected


_MODEL = Path(od._DEFAULT_MODEL)


@pytest.mark.skipif(not _MODEL.is_file(), reason="YOLOX model file not present")
def test_yolox_real_model_runs_on_blank_video(tmp_path):
    video = create_synthetic_test_video(tmp_path / "clip.mp4", has_motion=False, num_frames=6)
    res = od.detect_objects_in_video(video)
    assert res.error is None and res.engine == "yolox" and res.frames_sampled >= 1


def test_api_object_detect_and_report(auth_client, tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_MODEL_PATH", str(tmp_path / "absent.onnx"))
    r = auth_client.post("/api/cases", json={"case_number": "OBJ-API-1", "examiner": "Test Inspector"})
    cid = r.json()["case_id"]
    img = tmp_path / "e.dd"
    img.write_bytes(b"\x00" * 4096)
    evid = auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(img)}).json()["evidence_id"]

    import backend.main as main_mod
    video = create_synthetic_test_video(tmp_path / "seg.mp4", has_motion=True, num_frames=12)
    seg = Segment(evidence_id=evid, camera=0, frame_count=12, status=SegmentStatus.PARTIAL,
                  export_path=str(video), sha256="ab" * 32)
    main_mod.db.save_segment(seg)
    unexported = Segment(evidence_id=evid, camera=1, frame_count=1, status=SegmentStatus.UNCERTAIN)
    main_mod.db.save_segment(unexported)

    assert auth_client.post(f"/api/cases/{cid}/object-detect/{unexported.segment_id}").status_code == 400
    assert auth_client.post(f"/api/cases/{cid}/object-detect/nope").status_code == 404

    r = auth_client.post(f"/api/cases/{cid}/object-detect/{seg.segment_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "hog" and body["segment_id"] == seg.segment_id and body["export_sha256"] == "ab" * 32

    listed = auth_client.get(f"/api/cases/{cid}/object-detect").json()
    assert len(listed["results"]) == 1 and listed["engine_available"]["hog"] is True

    detail = auth_client.get(f"/api/cases/{cid}").json()
    assert any(a["action"] == "object_detection" for a in detail["audit"])

    pdf = auth_client.get(f"/api/cases/{cid}/report")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_report_section_wording():
    from backend import reporting
    S = reporting._styles()
    none = " ".join(getattr(f, "text", "") for f in reporting._object_section([], S))
    assert "Not run" in none
    flow = reporting._object_section([{
        "segment_id": "abcdef123", "label": "AI-Based Object Detection (YOLOX, COCO classes)", "frames_sampled": 10,
        "classes": {"person": {"frames_with": 4, "max_in_frame": 2, "first_time_s": 1.5}}}], S)
    text = " ".join(getattr(f, "text", "") for f in flow)
    assert "not identification" in text
