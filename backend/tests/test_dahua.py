"""
test_dahua.py — Unit tests for Dahua brand plugin.
"""

import pytest
from backend.acquisition import EvidenceImage
from backend.plugins.dahua import DahuaPlugin
from backend.plugins.unknown import UnknownPlugin

def test_dahua_detect(dahua_img_path):
    with EvidenceImage.open(dahua_img_path) as img:
        plugin = DahuaPlugin()
        confidence = plugin.detect(img)
        assert confidence >= 0.5

def test_dahua_carve(dahua_img_path):
    with EvidenceImage.open(dahua_img_path) as img:
        plugin = DahuaPlugin()
        frames, note = plugin.carve(img)
        assert len(frames) > 0
        for frame in frames:
            assert frame.brand == "dahua"
            assert frame.camera in [0, 1]
            assert frame.timestamp is not None
            assert frame.frame_size > 0

def test_dahua_list_recordings_unimplemented(dahua_img_path):
    with EvidenceImage.open(dahua_img_path) as img:
        plugin = DahuaPlugin()
        recs, note = plugin.list_recordings(img)
        assert recs == []
        assert "not implemented" in note.lower()

def test_unknown_plugin_ext4(foreign_img_path):
    with EvidenceImage.open(foreign_img_path) as img:
        plugin = UnknownPlugin()
        conf = plugin.detect(img)
        assert conf > 0.0
        details = plugin.version_hint()
        assert "ext4" in details.lower() or "filesystem" in details.lower() or "unsupported" in details.lower()
