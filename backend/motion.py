"""
motion.py — Basic Motion Detection via OpenCV frame differencing.

DECOUPLED POST-EXPORT ANALYSIS
===============================
This module provides basic, deterministic motion detection on exported MP4 video
segments. It compares consecutive video frames using pixel-level differencing.

Forensic Integrity Guarantees:
  - Read-only access: The exported video file and evidence image are never modified.
  - Decoupled from carving: Does not alter frame carving, reconstruction, or hashes.
  - Transparent labeling: Explicitly labeled as "Basic Motion Detection", NEVER as
    "AI Analytics" or "Machine Learning".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

MOTION_LABEL = "Basic Motion Detection"


@dataclass
class MotionDetectionResult:
    motion_detected: bool
    motion_frames: int
    total_frames: int
    motion_ratio: float
    summary: str
    label: str = MOTION_LABEL
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "motion_detected": self.motion_detected,
            "motion_frames": self.motion_frames,
            "total_frames": self.total_frames,
            "motion_ratio": round(self.motion_ratio, 4),
            "summary": self.summary,
            "label": self.label,
            "error": self.error,
        }


def detect_motion_in_video(
    video_path: str | Path,
    pixel_threshold: int = 25,
    min_changed_ratio: float = 0.015,
    min_motion_frames: int = 1,
) -> MotionDetectionResult:
    """
    Perform frame-differencing motion detection on an exported video segment.

    Algorithm:
      1. Open video stream in read-only mode via OpenCV VideoCapture.
      2. Convert consecutive frames to grayscale and apply Gaussian blur to suppress noise.
      3. Compute absolute difference between frame_n and frame_(n-1).
      4. Threshold the difference: pixels with delta >= pixel_threshold are flagged as changed.
      5. If changed pixels / total pixels >= min_changed_ratio, frame is counted as containing motion.
      6. Flag segment as motion_detected if motion_frames >= min_motion_frames.

    Args:
        video_path: Path to the exported MP4/video file.
        pixel_threshold: Grayscale intensity delta to count a pixel as changed (0-255). Default: 25.
        min_changed_ratio: Fraction of frame area that must change to count as a motion frame (default 1.5%).
        min_motion_frames: Minimum number of motion frames required to flag the segment (default 1).

    Returns:
        MotionDetectionResult with deterministic motion metrics.
    """
    path = Path(video_path)
    if not path.is_file():
        return MotionDetectionResult(
            motion_detected=False,
            motion_frames=0,
            total_frames=0,
            motion_ratio=0.0,
            summary=f"{MOTION_LABEL}: File not found ({path})",
            error=f"File not found: {path}",
        )

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return MotionDetectionResult(
            motion_detected=False,
            motion_frames=0,
            total_frames=0,
            motion_ratio=0.0,
            summary=f"{MOTION_LABEL}: Unable to open video container with OpenCV",
            error="Could not open video file",
        )

    prev_gray: Optional[np.ndarray] = None
    total_frames = 0
    motion_frames = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            total_frames += 1

            # Convert to grayscale and blur
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is not None:
                # Compute frame difference
                delta = cv2.absdiff(prev_gray, blurred)
                thresh = cv2.threshold(delta, pixel_threshold, 255, cv2.THRESH_BINARY)[1]
                # Dilate to fill small gaps
                thresh = cv2.dilate(thresh, None, iterations=2)

                changed_pixels = int(np.count_nonzero(thresh))
                frame_pixels = thresh.size
                changed_ratio = changed_pixels / frame_pixels if frame_pixels else 0.0

                if changed_ratio >= min_changed_ratio:
                    motion_frames += 1

            prev_gray = blurred

    except Exception as exc:
        log.warning("Motion detection encountered frame read error: %s", exc)
        return MotionDetectionResult(
            motion_detected=False,
            motion_frames=motion_frames,
            total_frames=total_frames,
            motion_ratio=0.0,
            summary=f"{MOTION_LABEL}: Error during frame analysis: {exc}",
            error=str(exc),
        )
    finally:
        cap.release()

    motion_ratio = (motion_frames / total_frames) if total_frames > 0 else 0.0
    motion_detected = motion_frames >= min_motion_frames

    if motion_detected:
        pct = motion_ratio * 100
        summary = (
            f"{MOTION_LABEL}: Motion detected across {motion_frames} of {total_frames} frames ({pct:.1f}%)."
        )
    else:
        summary = (
            f"{MOTION_LABEL}: No significant motion detected across {total_frames} frames."
        )

    return MotionDetectionResult(
        motion_detected=motion_detected,
        motion_frames=motion_frames,
        total_frames=total_frames,
        motion_ratio=motion_ratio,
        summary=summary,
    )


def create_synthetic_test_video(
    output_path: str | Path,
    has_motion: bool = True,
    num_frames: int = 30,
    width: int = 320,
    height: int = 240,
    fps: int = 10,
) -> Path:
    """
    Generate an uncompressed or standard MP4 test video for deterministic unit testing.

    If has_motion=False:
      Produces completely static frames (gray background).
    If has_motion=True:
      Produces static background with a contrasting white block moving across frames.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))

    if not writer.isOpened():
        # Fallback to MJPG in .avi if mp4v codec is not available
        alt_path = path.with_suffix(".avi")
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(str(alt_path), fourcc, fps, (width, height))
        path = alt_path

    try:
        for i in range(num_frames):
            frame = np.full((height, width, 3), 60, dtype=np.uint8)
            if has_motion and i > 5:
                # Draw a moving white rectangle
                x_pos = int((i - 5) * 8) % (width - 50)
                y_pos = int(height / 2 - 25)
                cv2.rectangle(frame, (x_pos, y_pos), (x_pos + 40, y_pos + 40), (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()

    return path
