"""
test_uniview.py — Tests for the Uniview detection-only stub plugin.
"""

import os

import pytest

from backend.acquisition import EvidenceImage
from backend.plugins.uniview import UniviewPlugin


def test_uniview_detect_random_data_low_confidence(temp_dir):
    path = os.path.join(temp_dir, "random_uniview_probe.dd")
    with open(path, "wb") as f:
        f.write(os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        confidence = UniviewPlugin().detect(img)
    assert confidence == 0.0


def test_uniview_detect_foreign_image_low_confidence(foreign_img_path):
    with EvidenceImage.open(foreign_img_path) as img:
        confidence = UniviewPlugin().detect(img)
    assert confidence == 0.0


def test_uniview_carve_raises_not_implemented():
    plugin = UniviewPlugin()
    with pytest.raises(NotImplementedError, match="detection only"):
        plugin.carve(None)
