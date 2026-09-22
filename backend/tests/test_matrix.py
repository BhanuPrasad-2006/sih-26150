"""
test_matrix.py — Tests for the Matrix detection-only stub plugin.
"""

import os

import pytest

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


def test_matrix_carve_raises_not_implemented():
    plugin = MatrixPlugin()
    with pytest.raises(NotImplementedError, match="detection only"):
        plugin.carve(None)
