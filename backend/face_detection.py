"""
face_detection.py — Face detection via OpenCV's YuNet CNN (cv2.FaceDetectorYN).

DECOUPLED POST-EXPORT ANALYSIS
===============================
This module provides face detection on exported MP4 video segments, following
the exact same architecture as motion.py: read-only, decoupled from carving,
never touches the evidence image or the export file.

What this genuinely is:
  - YuNet (face_detection_yunet_2023mar.onnx) is a small convolutional neural
    network published by OpenCV's own model zoo (github.com/opencv/opencv_zoo).
    Running it through cv2.dnn is a real, deep-learning-based face detector —
    unlike motion.py's classical frame differencing, "AI-based" is an accurate
    label here.
  - It detects the PRESENCE and location (bounding boxes) of faces only.

What this is explicitly NOT:
  - NOT face recognition / identification. It never attempts to determine WHO
    a detected face belongs to, and carries no reference database of known
    individuals. Detected faces are reported as counts/boxes only.
  - NOT a claim of forensic-grade accuracy. Like any face detector, it can
    miss faces (occlusion, extreme angles, low resolution, poor lighting) or
    flag false positives. Results must be independently reviewed, never cited
    as sole proof that a person was or was not present.

Forensic Integrity Guarantees (same as motion.py):
  - Read-only access: the exported video file and evidence image are never modified.
  - Decoupled from carving: does not alter frame carving, reconstruction, or hashes.
  - Transparent labeling: explicitly labeled "AI-Based Face Detection (OpenCV
    YuNet)", never implying recognition/identification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

FACE_DETECTION_LABEL = "AI-Based Face Detection (OpenCV YuNet)"

_MODEL_PATH = Path(__file__).parent / "cv_models" / "face_detection_yunet_2023mar.onnx"

# Analyzing every single frame of a video is expensive for a CNN detector;
# sample every Nth frame instead. This is a coverage/speed trade-off, not an
# accuracy claim — a face present only in skipped frames will be missed.
DEFAULT_FRAME_STRIDE = 5
DEFAULT_SCORE_THRESHOLD = 0.7
DEFAULT_NMS_THRESHOLD = 0.3


@dataclass
class FaceDetectionResult:
    faces_detected: bool
    frames_with_faces: int
    frames_sampled: int
    total_frames: int
    max_faces_in_single_frame: int
    summary: str
    label: str = FACE_DETECTION_LABEL
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "faces_detected": self.faces_detected,
            "frames_with_faces": self.frames_with_faces,
            "frames_sampled": self.frames_sampled,
            "total_frames": self.total_frames,
            "max_faces_in_single_frame": self.max_faces_in_single_frame,
            "summary": self.summary,
            "label": self.label,
            "error": self.error,
        }


def model_available() -> bool:
    """True if the YuNet ONNX model file is present on disk."""
    return _MODEL_PATH.is_file()


def detect_faces_in_video(
    video_path: str | Path,
    frame_stride: int = DEFAULT_FRAME_STRIDE,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
) -> FaceDetectionResult:
    """
    Run YuNet face detection on every `frame_stride`-th frame of an exported
    video segment.

    Args:
        video_path: Path to the exported MP4/video file.
        frame_stride: Analyze every Nth frame (default 5) — a speed/coverage
            trade-off, not an accuracy claim.
        score_threshold: Minimum detection confidence to count as a face (0-1).
        nms_threshold: Non-max-suppression IoU threshold for de-duplicating
            overlapping detections of the same face.

    Returns:
        FaceDetectionResult with deterministic per-video counts.
    """
    path = Path(video_path)
    if not path.is_file():
        return FaceDetectionResult(
            faces_detected=False, frames_with_faces=0, frames_sampled=0, total_frames=0,
            max_faces_in_single_frame=0,
            summary=f"{FACE_DETECTION_LABEL}: File not found ({path})",
            error=f"File not found: {path}",
        )

    if not model_available():
        return FaceDetectionResult(
            faces_detected=False, frames_with_faces=0, frames_sampled=0, total_frames=0,
            max_faces_in_single_frame=0,
            summary=(
                f"{FACE_DETECTION_LABEL}: Model file missing "
                f"({_MODEL_PATH.name}) — face detection is unavailable."
            ),
            error=f"Model file not found: {_MODEL_PATH}",
        )

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return FaceDetectionResult(
            faces_detected=False, frames_with_faces=0, frames_sampled=0, total_frames=0,
            max_faces_in_single_frame=0,
            summary=f"{FACE_DETECTION_LABEL}: Unable to open video container with OpenCV",
            error="Could not open video file",
        )

    total_frames = 0
    frames_sampled = 0
    frames_with_faces = 0
    max_faces_in_single_frame = 0
    detector = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            total_frames += 1

            if (total_frames - 1) % frame_stride != 0:
                continue

            height, width = frame.shape[:2]
            if width == 0 or height == 0:
                continue

            if detector is None:
                detector = cv2.FaceDetectorYN_create(
                    str(_MODEL_PATH), "", (width, height),
                    score_threshold, nms_threshold, 5000,
                )
            detector.setInputSize((width, height))

            _, faces = detector.detect(frame)
            frames_sampled += 1
            face_count = 0 if faces is None else len(faces)
            if face_count > 0:
                frames_with_faces += 1
                max_faces_in_single_frame = max(max_faces_in_single_frame, face_count)

    except Exception as exc:
        log.warning("Face detection encountered a frame read/inference error: %s", exc)
        return FaceDetectionResult(
            faces_detected=False, frames_with_faces=frames_with_faces,
            frames_sampled=frames_sampled, total_frames=total_frames,
            max_faces_in_single_frame=max_faces_in_single_frame,
            summary=f"{FACE_DETECTION_LABEL}: Error during frame analysis: {exc}",
            error=str(exc),
        )
    finally:
        cap.release()

    faces_detected = frames_with_faces > 0
    if faces_detected:
        pct = (frames_with_faces / frames_sampled * 100) if frames_sampled else 0.0
        summary = (
            f"{FACE_DETECTION_LABEL}: Face(s) detected in {frames_with_faces} of "
            f"{frames_sampled} sampled frames ({pct:.1f}%); up to "
            f"{max_faces_in_single_frame} face(s) in a single frame. "
            f"Detection only — no identity/recognition was attempted."
        )
    else:
        summary = (
            f"{FACE_DETECTION_LABEL}: No faces detected across {frames_sampled} sampled frames "
            f"of {total_frames} total. Does not prove no person was present — occluded, "
            f"angled, or low-resolution faces can be missed."
        )

    return FaceDetectionResult(
        faces_detected=faces_detected,
        frames_with_faces=frames_with_faces,
        frames_sampled=frames_sampled,
        total_frames=total_frames,
        max_faces_in_single_frame=max_faces_in_single_frame,
        summary=summary,
    )
