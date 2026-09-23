"""
face_search.py — Face similarity search across recovered video segments.

Given a reference photo of a person, this searches for visually similar
faces across every segment already indexed for a case, using OpenCV's YuNet
(face detection/localization) + SFace (face embedding/recognition) models —
both published by OpenCV's own model zoo (github.com/opencv/opencv_zoo).

READ BEFORE TRUSTING A RESULT
=============================
This is a real, working similarity search, but it is NOT identity proof:

  - A high similarity score is a CANDIDATE for human review, never a
    confirmed match. This project manually verified SFace against three
    distinct synthetic (AI-generated, not-a-real-person) faces during
    development: two clearly DIFFERENT faces scored 0.399 cosine similarity —
    ABOVE OpenCV's own commonly-cited "same identity" reference threshold of
    0.363. That is a real, observed false-match risk at typical operating
    thresholds, not a hypothetical caveat.
  - Accuracy depends heavily on image quality, pose, lighting angle, and
    video compression artifacts in the exported segment. A low score does
    NOT prove the person was absent — it can just mean a poor camera angle.
  - This must never be presented, alone, as proof of identity in a report.
    Always corroborate with independent evidence and expert review.

Search only runs against segments that have already been indexed (their
exported video was run through index_faces_for_search, typically as a side
effect of running face detection — see main.py). This avoids re-decoding
every video on every search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from backend.face_detection import DEFAULT_FRAME_STRIDE

log = logging.getLogger(__name__)

FACE_SEARCH_LABEL = "Face Similarity Search (OpenCV YuNet + SFace)"

_DETECTOR_MODEL_PATH = Path(__file__).parent / "cv_models" / "face_detection_yunet_2023mar.onnx"
_RECOGNIZER_MODEL_PATH = Path(__file__).parent / "cv_models" / "face_recognition_sface_2021dec.onnx"

# OpenCV's own commonly-cited reference threshold for "same identity" at a
# specific false-accept-rate operating point on the SFace benchmark. Shown to
# the examiner as context ONLY — see the module docstring for why a score
# above this is still a candidate, not a confirmed match.
REFERENCE_MATCH_THRESHOLD = 0.363


@dataclass
class FaceEmbeddingRecord:
    frame_offset_seconds: float
    bbox: list[float]           # [x, y, w, h] in the source frame
    embedding: list[float]


@dataclass
class FaceSearchMatch:
    segment_id: str
    frame_offset_seconds: float
    bbox: list[float]
    similarity: float

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "frame_offset_seconds": round(self.frame_offset_seconds, 3),
            "bbox": self.bbox,
            "similarity": round(self.similarity, 4),
            "above_reference_threshold": self.similarity >= REFERENCE_MATCH_THRESHOLD,
        }


def models_available() -> bool:
    return _DETECTOR_MODEL_PATH.is_file() and _RECOGNIZER_MODEL_PATH.is_file()


def _create_models(input_size: tuple[int, int]):
    detector = cv2.FaceDetectorYN_create(
        str(_DETECTOR_MODEL_PATH), "", input_size, 0.7, 0.3, 5000,
    )
    recognizer = cv2.FaceRecognizerSF_create(str(_RECOGNIZER_MODEL_PATH), "")
    return detector, recognizer


def extract_embedding_from_image_bytes(image_bytes: bytes) -> Optional[list[float]]:
    """
    Extract a face embedding from a reference photo (the person to search
    for). Uses the largest detected face if more than one is present.
    Returns None if no face is found or the model files are unavailable.
    """
    if not models_available():
        return None
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return None
    height, width = img.shape[:2]
    if width == 0 or height == 0:
        return None

    detector, recognizer = _create_models((width, height))
    _, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None

    # Largest face by bounding-box area — the most likely intentional subject
    # of a reference photo (vs. incidental bystanders in the background).
    largest = max(faces, key=lambda f: float(f[2]) * float(f[3]))
    aligned = recognizer.alignCrop(img, largest)
    feature = recognizer.feature(aligned)
    return feature.flatten().tolist()


def index_faces_for_search(
    video_path: str | Path,
    frame_stride: int = DEFAULT_FRAME_STRIDE,
) -> list[FaceEmbeddingRecord]:
    """
    Detect faces in an exported video and extract an embedding for each,
    for later similarity search. Read-only; does not modify the video file.
    """
    if not models_available():
        return []

    path = Path(video_path)
    if not path.is_file():
        return []

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    records: list[FaceEmbeddingRecord] = []
    frame_index = 0
    detector = None
    recognizer = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            current_index = frame_index
            frame_index += 1

            if current_index % frame_stride != 0:
                continue

            height, width = frame.shape[:2]
            if width == 0 or height == 0:
                continue

            if detector is None:
                detector, recognizer = _create_models((width, height))
            detector.setInputSize((width, height))

            _, faces = detector.detect(frame)
            if faces is None:
                continue

            offset_seconds = (current_index / fps) if fps > 0 else float(current_index)
            for face in faces:
                try:
                    aligned = recognizer.alignCrop(frame, face)
                    feature = recognizer.feature(aligned)
                except Exception as exc:
                    log.debug("Skipping one face (align/embed failed): %s", exc)
                    continue
                records.append(FaceEmbeddingRecord(
                    frame_offset_seconds=offset_seconds,
                    bbox=[float(v) for v in face[:4]],
                    embedding=feature.flatten().tolist(),
                ))
    except Exception as exc:
        log.warning("Face indexing encountered a frame read/inference error: %s", exc)
    finally:
        cap.release()

    return records


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embeddings (same metric SFace.match() uses)."""
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def rank_matches(
    reference_embedding: list[float],
    candidates: list[tuple[str, FaceEmbeddingRecord]],
    top_k: int = 50,
) -> list[FaceSearchMatch]:
    """
    Pure ranking logic (no I/O, no model calls) — given a reference embedding
    and a list of (segment_id, FaceEmbeddingRecord) candidates already
    extracted/loaded, return the top_k most similar, sorted descending.
    Kept separate from extraction so this can be unit-tested without models.
    """
    scored = [
        FaceSearchMatch(
            segment_id=seg_id,
            frame_offset_seconds=rec.frame_offset_seconds,
            bbox=rec.bbox,
            similarity=cosine_similarity(reference_embedding, rec.embedding),
        )
        for seg_id, rec in candidates
    ]
    scored.sort(key=lambda m: m.similarity, reverse=True)
    return scored[:top_k]
