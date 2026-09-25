"""
object_detection.py — Object detection on exported video segments.

DECOUPLED POST-EXPORT ANALYSIS (same rules as motion.py / face_detection.py):
read-only on the exported file, never touches the evidence image, carving,
reconstruction or hashes.

Two engines, chosen automatically and ALWAYS named in the result label:

  1. YOLOX (deep learning, COCO 80 classes) through cv2.dnn — used when an ONNX
     model file is present (cv_models/object_detection_yolox_2022nov.onnx, from
     the OpenCV model zoo, Apache-2.0, or a path in $OBJECT_MODEL_PATH).
     This is genuine AI-based object detection.
  2. OpenCV's built-in HOG + linear SVM pedestrian detector — used when no
     model file is present. It needs no download and finds PERSONS ONLY. It is
     classical computer vision (1990s-2000s), not machine-learning "AI
     analytics" in the modern sense, and it produces false positives and
     misses; it is labelled that way.

What this is NOT: a claim of forensic-grade accuracy, or of identification.
A detection means "a detector scored a region above its threshold"; the
absence of a detection does not prove the object was absent. Frames are
sampled (every Nth), so an object visible only in skipped frames is missed.
Results must be reviewed by a person.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from backend.model_integrity import verify_model

log = logging.getLogger(__name__)

YOLOX_LABEL = "AI-Based Object Detection (YOLOX, COCO classes)"
HOG_LABEL = "Person Detection (OpenCV HOG+SVM — classical, not deep learning; persons only)"

_DEFAULT_MODEL = Path(__file__).parent / "cv_models" / "object_detection_yolox_2022nov.onnx"

DEFAULT_FRAME_STRIDE = 5
DEFAULT_SCORE_THRESHOLD = 0.5
DEFAULT_NMS_THRESHOLD = 0.45
YOLOX_INPUT_SIZE = 640
YOLOX_STRIDES = (8, 16, 32)
HOG_MAX_WIDTH = 640
HOG_MIN_WEIGHT = 0.5          # SVM margin below this is treated as noise

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
)


def model_path() -> Path:
    env = os.environ.get("OBJECT_MODEL_PATH", "").strip()
    return Path(env) if env else _DEFAULT_MODEL


def model_available() -> bool:
    return model_path().is_file()


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ClassStats:
    frames_with: int = 0
    max_in_frame: int = 0
    best_score: float = 0.0
    first_time_s: Optional[float] = None
    first_frame: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "frames_with": self.frames_with,
            "max_in_frame": self.max_in_frame,
            "best_score": round(self.best_score, 3),
            "first_time_s": None if self.first_time_s is None else round(self.first_time_s, 2),
            "first_frame": self.first_frame,
        }


@dataclass
class ObjectDetectionResult:
    engine: str                       # "yolox" | "hog"
    label: str
    objects_detected: bool
    frames_sampled: int
    total_frames: int
    classes: dict[str, ClassStats] = field(default_factory=dict)
    summary: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "label": self.label,
            "objects_detected": self.objects_detected,
            "frames_sampled": self.frames_sampled,
            "total_frames": self.total_frames,
            "classes": {k: v.to_dict() for k, v in sorted(self.classes.items())},
            "summary": self.summary,
            "error": self.error,
        }


# ── YOLOX pre/post-processing (pure numpy, unit-tested without a model) ───────

def letterbox(frame: np.ndarray, size: int = YOLOX_INPUT_SIZE) -> tuple[np.ndarray, float]:
    """Resize keeping aspect ratio, pad bottom/right with 114 (YOLOX convention)."""
    h, w = frame.shape[:2]
    ratio = min(size / h, size / w)
    nh, nw = max(1, int(round(h * ratio))), max(1, int(round(w * ratio)))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[:nh, :nw] = resized
    return canvas, ratio


def _grids_and_strides(size: int = YOLOX_INPUT_SIZE) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for s in YOLOX_STRIDES:
        n = size // s
        xs, ys = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xs, ys), axis=2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids, 0).astype(np.float32), np.concatenate(strides, 0).astype(np.float32)


def decode_yolox(
    output: np.ndarray,
    ratio: float,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    size: int = YOLOX_INPUT_SIZE,
) -> list[tuple[int, float, tuple[float, float, float, float]]]:
    """
    Turn a raw YOLOX output tensor of shape (1, N, 85) or (N, 85) into
    [(class_id, score, (x1, y1, x2, y2))] in ORIGINAL-frame pixels.

    Each row is (cx, cy, w, h, objectness, 80 class scores) in grid-cell units
    that must be decoded: centre = (raw + grid) * stride, size = exp(raw) * stride.
    Score = objectness * class score. Boxes are de-duplicated per class by NMS.
    """
    pred = np.asarray(output, dtype=np.float32)
    if pred.ndim == 3:
        pred = pred[0]
    grids, strides = _grids_and_strides(size)
    if pred.ndim != 2 or pred.shape[1] != 5 + len(COCO_CLASSES) or pred.shape[0] != len(grids):
        raise ValueError(f"Unexpected YOLOX output shape {tuple(np.asarray(output).shape)}")

    xy = (pred[:, 0:2] + grids) * strides
    wh = np.exp(pred[:, 2:4]) * strides
    scores_all = pred[:, 4:5] * pred[:, 5:]
    class_ids = scores_all.argmax(axis=1)
    scores = scores_all[np.arange(len(pred)), class_ids]
    keep = scores >= score_threshold
    if not keep.any():
        return []

    xy, wh, class_ids, scores = xy[keep], wh[keep], class_ids[keep], scores[keep]
    x1y1 = (xy - wh / 2) / ratio
    boxes_xyxy = np.concatenate([x1y1, (xy + wh / 2) / ratio], axis=1)

    results: list[tuple[int, float, tuple[float, float, float, float]]] = []
    for cid in np.unique(class_ids):
        idx = np.where(class_ids == cid)[0]
        b = boxes_xyxy[idx]
        rects = [[float(x1), float(y1), float(x2 - x1), float(y2 - y1)] for x1, y1, x2, y2 in b]
        picked = cv2.dnn.NMSBoxes(rects, scores[idx].astype(float).tolist(), score_threshold, nms_threshold)
        for p in np.array(picked).reshape(-1):
            i = idx[int(p)]
            results.append((int(cid), float(scores[i]), tuple(float(v) for v in boxes_xyxy[i])))
    return results


# ── Detection over a video ────────────────────────────────────────────────────

def _empty(engine: str, label: str, summary: str, error: Optional[str] = None,
           total: int = 0, sampled: int = 0) -> ObjectDetectionResult:
    return ObjectDetectionResult(engine=engine, label=label, objects_detected=False,
                                 frames_sampled=sampled, total_frames=total,
                                 summary=summary, error=error)


def detect_objects_in_video(
    video_path: str | Path,
    frame_stride: int = DEFAULT_FRAME_STRIDE,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    force_engine: Optional[str] = None,        # "yolox" | "hog" (tests / examiner override)
) -> ObjectDetectionResult:
    path = Path(video_path)
    use_yolox = model_available() if force_engine is None else force_engine == "yolox"
    engine, label = ("yolox", YOLOX_LABEL) if use_yolox else ("hog", HOG_LABEL)

    if not path.is_file():
        return _empty(engine, label, f"{label}: File not found ({path})", f"File not found: {path}")
    if use_yolox and not model_available():
        return _empty(engine, label, f"{label}: model file missing ({model_path().name})",
                      f"Model file not found: {model_path()}")

    if use_yolox:
        ok_model, model_msg = verify_model(model_path())
        if not ok_model:
            return _empty(engine, label, f"{label}: {model_msg}", model_msg)

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return _empty(engine, label, f"{label}: unable to open video container with OpenCV",
                      "Could not open video file")

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    net = None
    hog = None
    if use_yolox:
        try:
            net = cv2.dnn.readNetFromONNX(str(model_path()))
        except Exception as exc:                           # corrupt / incompatible model
            cap.release()
            return _empty(engine, label, f"{label}: could not load model: {exc}", str(exc))
    else:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    stats: dict[str, ClassStats] = {}
    total = sampled = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            total += 1
            if (total - 1) % max(1, frame_stride) != 0:
                continue
            sampled += 1

            if net is not None:
                canvas, ratio = letterbox(frame)
                blob = cv2.dnn.blobFromImage(canvas, 1.0, (YOLOX_INPUT_SIZE, YOLOX_INPUT_SIZE),
                                             (0, 0, 0), swapRB=False, crop=False)
                net.setInput(blob)
                dets = decode_yolox(net.forward(), ratio, score_threshold, nms_threshold)
                per_frame = [(COCO_CLASSES[c], s) for c, s, _ in dets]
            else:
                h, w = frame.shape[:2]
                scale = min(1.0, HOG_MAX_WIDTH / w)
                small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame
                _, weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
                per_frame = [("person", float(wt)) for wt in np.array(weights).reshape(-1)
                             if float(wt) >= HOG_MIN_WEIGHT]

            counts: dict[str, int] = {}
            for name, score in per_frame:
                counts[name] = counts.get(name, 0) + 1
                st = stats.setdefault(name, ClassStats())
                st.best_score = max(st.best_score, score)
            for name, n in counts.items():
                st = stats[name]
                st.frames_with += 1
                st.max_in_frame = max(st.max_in_frame, n)
                if st.first_frame is None:
                    st.first_frame = total - 1
                    st.first_time_s = (total - 1) / fps if fps > 0 else None
    except Exception as exc:
        log.warning("Object detection error: %s", exc)
        return ObjectDetectionResult(engine=engine, label=label, objects_detected=bool(stats),
                                     frames_sampled=sampled, total_frames=total, classes=stats,
                                     summary=f"{label}: error during frame analysis: {exc}", error=str(exc))
    finally:
        cap.release()

    if stats:
        parts = [f"{name} in {st.frames_with}/{sampled} sampled frames (up to {st.max_in_frame} at once)"
                 for name, st in sorted(stats.items(), key=lambda kv: -kv[1].frames_with)]
        summary = f"{label}: " + "; ".join(parts) + ". Automated detection, review by a person is required."
    else:
        summary = (f"{label}: nothing detected across {sampled} sampled frames of {total}. "
                   f"Does not prove nothing was present.")
    return ObjectDetectionResult(engine=engine, label=label, objects_detected=bool(stats),
                                 frames_sampled=sampled, total_frames=total, classes=stats,
                                 summary=summary)
