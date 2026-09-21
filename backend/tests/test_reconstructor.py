"""
test_reconstructor.py — Unit tests for reconstructor logic.
"""

import pytest
from backend.acquisition import EvidenceImage
from backend.plugins.dahua import DahuaPlugin
from backend.reconstructor import reconstruct_segments, label_all

def test_reconstruct_segments(dahua_img_path):
    with EvidenceImage.open(dahua_img_path) as img:
        plugin = DahuaPlugin()
        raw_frames, _ = plugin.carve(img)
        segments = reconstruct_segments(raw_frames, ev_id="EVID-TEST-001", brand="Dahua")
        assert len(segments) > 0
        for seg in segments:
            assert seg.evidence_id == "EVID-TEST-001"
            assert seg.camera in [0, 1]
            assert seg.frame_count > 0
            assert seg.status is not None
