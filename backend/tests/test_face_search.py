"""
test_face_search.py — Tests for face similarity search.

Note: consistent with this project's synthetic-data-only test convention,
no real (or AI-generated) photo of a face is committed as a test fixture
here. The ranking/similarity math (rank_matches, cosine_similarity) is pure
and is tested directly with synthetic vectors — no image or model needed.
The extraction/model-loading path is exercised with non-face images to
verify it fails closed (returns None) rather than crashing.

Positive end-to-end verification — that the models genuinely detect and
correctly discriminate real faces, and the concrete false-match example
cited in face_search.py's docstring — was done manually during development
using AI-generated (not-a-real-person) reference images, not committed here.
"""

import io

import cv2
import numpy as np
import pytest

from backend.face_search import (
    FACE_SEARCH_LABEL,
    REFERENCE_MATCH_THRESHOLD,
    FaceEmbeddingRecord,
    cosine_similarity,
    extract_embedding_from_image_bytes,
    models_available,
    rank_matches,
)


def test_face_search_models_are_available():
    assert models_available() is True


def test_cosine_similarity_identical_vectors():
    v = [1.0, 2.0, 3.0, 4.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_does_not_raise():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_rank_matches_sorts_descending_by_similarity():
    reference = [1.0, 0.0, 0.0]
    candidates = [
        ("seg-low", FaceEmbeddingRecord(1.0, [0, 0, 10, 10], [0.1, 0.9, 0.0])),
        ("seg-high", FaceEmbeddingRecord(2.0, [0, 0, 10, 10], [0.99, 0.01, 0.0])),
        ("seg-mid", FaceEmbeddingRecord(3.0, [0, 0, 10, 10], [0.5, 0.5, 0.0])),
    ]

    results = rank_matches(reference, candidates)

    assert [m.segment_id for m in results] == ["seg-high", "seg-mid", "seg-low"]
    assert results[0].similarity > results[1].similarity > results[2].similarity


def test_rank_matches_respects_top_k():
    reference = [1.0, 0.0]
    candidates = [
        (f"seg-{i}", FaceEmbeddingRecord(float(i), [0, 0, 1, 1], [1.0, float(i)]))
        for i in range(10)
    ]

    results = rank_matches(reference, candidates, top_k=3)

    assert len(results) == 3


def test_rank_matches_empty_candidates_returns_empty():
    assert rank_matches([1.0, 0.0], []) == []


def test_reference_threshold_is_documented_and_reasonable():
    # Sanity check the constant is a real cosine-similarity value, not a stray default.
    assert 0.0 < REFERENCE_MATCH_THRESHOLD < 1.0


def test_extract_embedding_returns_none_for_faceless_image():
    """A non-face image (random noise) must return None, not crash or hallucinate a face."""
    noise = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", noise)
    assert ok
    result = extract_embedding_from_image_bytes(buf.tobytes())
    assert result is None


def test_extract_embedding_returns_none_for_corrupt_bytes():
    result = extract_embedding_from_image_bytes(b"not a real image")
    assert result is None


def test_face_search_api_rejects_faceless_reference_image(auth_client, tmp_path):
    """
    POST /api/cases/{case_id}/face-search must reject a reference photo with
    no detectable face, rather than crashing or silently searching with an
    empty embedding.
    """
    res = auth_client.post("/api/cases", json={"case_number": "FACESEARCH-TEST-001", "examiner": "Det. Sharma"})
    assert res.status_code == 200
    case_id = res.json()["case_id"]

    noise = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", noise)
    assert ok

    search_res = auth_client.post(
        f"/api/cases/{case_id}/face-search",
        files={"reference_image": ("noise.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
    )
    assert search_res.status_code == 400
    assert "no face" in search_res.json()["detail"].lower()
