"""
test_hikvision.py — Unit tests for Hikvision brand plugin.
"""

import pytest
from backend.acquisition import EvidenceImage
from backend.plugins.hikvision import HikvisionPlugin

def test_hikvision_detect(hikvision_img_path):
    with EvidenceImage.open(hikvision_img_path) as img:
        plugin = HikvisionPlugin()
        confidence = plugin.detect(img)
        assert confidence == 1.0

def test_hikvision_list_recordings_unimplemented(hikvision_img_path):
    with EvidenceImage.open(hikvision_img_path) as img:
        plugin = HikvisionPlugin()
        recs, note = plugin.list_recordings(img)
        assert recs == []
        assert "not implemented" in note.lower()

def test_hikvision_carve(hikvision_img_path):
    with EvidenceImage.open(hikvision_img_path) as img:
        plugin = HikvisionPlugin()
        frames, note = plugin.carve(img)
        assert isinstance(frames, list)
