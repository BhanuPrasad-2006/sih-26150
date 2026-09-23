"""
test_tplink.py — Tests for the TP-Link detection-only stub plugin.
"""

import os

from backend.acquisition import EvidenceImage
from backend.plugins.tplink import TPLinkPlugin
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE


def test_tplink_detect_random_data_zero_confidence(temp_dir):
    path = os.path.join(temp_dir, "random_tplink_probe.dd")
    with open(path, "wb") as f:
        f.write(os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        confidence = TPLinkPlugin().detect(img)
    assert confidence == 0.0


def test_tplink_detect_foreign_image_zero_confidence(foreign_img_path):
    with EvidenceImage.open(foreign_img_path) as img:
        confidence = TPLinkPlugin().detect(img)
    assert confidence == 0.0


def test_tplink_detect_marker_found_reports_low_confidence(temp_dir):
    """
    A vendor-name string hit must report low confidence — never enough to
    trigger a scan (MIN_PLUGIN_CONFIDENCE) — since no on-disk format is
    verified for this brand.
    """
    path = os.path.join(temp_dir, "tplink_marker.dd")
    with open(path, "wb") as f:
        f.write(b"\x00" * 512 + b"TP-LINK VIGI NVR1104H-4P" + os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        confidence = TPLinkPlugin().detect(img)
    assert 0.0 < confidence < MIN_PLUGIN_CONFIDENCE


def test_tplink_carve_returns_empty_without_raising():
    """
    carve() must honor the BrandPlugin contract (base.py): never raise, return
    ([], note) instead — so a future confidence bump can't surface as an
    opaque "Unexpected error" through the scan pipeline.
    """
    plugin = TPLinkPlugin()
    frames, note = plugin.carve(None)
    assert frames == []
    assert "detection only" in note.lower()


def test_tplink_list_recordings_returns_empty_without_raising():
    plugin = TPLinkPlugin()
    frames, note = plugin.list_recordings(None)
    assert frames == []
    assert "not implemented" in note.lower()


def test_tplink_display_name_labelled_unverified():
    plugin = TPLinkPlugin()
    assert "detection-only" in plugin.display_name.lower()
    assert "unverified" in plugin.display_name.lower()
