"""
test_matrix.py — Tests for the Matrix detection-only stub plugin.
"""

import os

from backend.acquisition import EvidenceImage
from backend.plugins.matrix import MatrixPlugin


def test_matrix_detect_random_data_low_confidence(temp_dir):
    path = os.path.join(temp_dir, "random_matrix_probe.dd")
    with open(path, "wb") as f:
        f.write(os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        confidence = MatrixPlugin().detect(img)
    assert confidence == 0.0


def test_matrix_detect_foreign_image_low_confidence(foreign_img_path):
    with EvidenceImage.open(foreign_img_path) as img:
        confidence = MatrixPlugin().detect(img)
    assert confidence == 0.0


def test_matrix_carve_returns_empty_without_raising():
    """
    carve() must honor the BrandPlugin contract (base.py): never raise, return
    ([], note) instead — so a future confidence bump can't surface as an
    opaque "Unexpected error" through the scan pipeline.
    """
    plugin = MatrixPlugin()
    frames, note = plugin.carve(None)
    assert frames == []
    assert "detection only" in note.lower()
