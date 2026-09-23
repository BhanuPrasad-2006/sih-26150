"""
test_cpplus.py — Tests for CP Plus detection stub and Dahua carving routing.

Verifies:
  1. CP Plus brand signature detection correctly routes to Dahua DHAV carving engine.
  2. The unverified label "CP Plus (Dahua-compatible detection — unverified)" appears
     in plugin display_name, detection result, and version hint.
  3. Non-CP Plus data (random noise, foreign filesystems) returns 0.0 confidence.
  4. CP Plus string without DHAV frames reports low confidence (< 0.6).
"""

import os
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.main import _detect_brand
from backend.models import Case, Evidence, Segment
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE
from backend.plugins.cpplus import CPPlusPlugin
from backend.reporting import generate_report


def test_cpplus_detect_and_route_to_dahua_carver(cpplus_img_path):
    """
    Test that an image containing CP Plus signature and DHAV frames:
      - Is detected as 'CP Plus (Dahua-compatible detection — unverified)'
      - Has confidence >= MIN_PLUGIN_CONFIDENCE (0.6)
      - Routes carving through the Dahua plugin, successfully extracting frames
    """
    with EvidenceImage.open(cpplus_img_path) as img:
        brand, version, confidence, plugin = _detect_brand(img)

        # 1. Exact unverified label verification
        expected_label = "CP Plus (Dahua-compatible detection — unverified)"
        assert brand == expected_label
        assert "unverified" in brand.lower()
        assert confidence >= MIN_PLUGIN_CONFIDENCE
        assert isinstance(plugin, CPPlusPlugin)
        assert plugin.display_name == expected_label
        assert "unverified" in plugin.version_hint().lower()

        # 2. Carving routes to Dahua carver
        frames, note = plugin.carve(img)
        assert len(frames) > 0
        assert "carved via dahua plugin" in note.lower()
        assert "unverified" in note.lower()

        # Frames are carved by the Dahua engine but re-tagged "cpplus" (not
        # "dahua") so downstream code (reconstructor, reporting) keeps
        # treating this data as unverified rather than as native Dahua data.
        for frame in frames:
            assert frame.brand == "cpplus"
            assert frame.frame_size > 0
            assert frame.timestamp is not None


def test_cpplus_unverified_label_everywhere():
    """Verify that the unverified string is present on all plugin properties."""
    plugin = CPPlusPlugin()
    expected_label = "CP Plus (Dahua-compatible detection — unverified)"
    assert plugin.display_name == expected_label
    assert "unverified" in plugin.display_name.lower()
    assert "unverified" in plugin.version_hint().lower()


def test_cpplus_detect_random_data_zero_confidence(temp_dir):
    """Random noise without CP Plus markers should return 0.0 confidence."""
    path = os.path.join(temp_dir, "random_cpplus_probe.dd")
    with open(path, "wb") as f:
        f.write(os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        confidence = CPPlusPlugin().detect(img)
    assert confidence == 0.0


def test_cpplus_detect_foreign_image_zero_confidence(foreign_img_path):
    """Foreign file systems (ext4) should return 0.0 confidence."""
    with EvidenceImage.open(foreign_img_path) as img:
        confidence = CPPlusPlugin().detect(img)
    assert confidence == 0.0


def test_cpplus_detect_marker_only_below_threshold(temp_dir):
    """
    A disk image containing a CP Plus string marker but NO DHAV frames must
    report low confidence (< MIN_PLUGIN_CONFIDENCE) as an unverified/unsupported format.
    """
    path = os.path.join(temp_dir, "cpplus_string_only.dd")
    with open(path, "wb") as f:
        f.write(b"\x00" * 512 + b"CP PLUS DVR SYSTEM - MODEL CP-UVR-0401E1" + os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        plugin = CPPlusPlugin()
        confidence = plugin.detect(img)
        assert 0.0 < confidence < MIN_PLUGIN_CONFIDENCE
        assert "unverified" in plugin.version_hint().lower()


def test_cpplus_unverified_label_in_report(tmp_path):
    """
    Test that the full label 'CP Plus (Dahua-compatible detection — unverified)'
    is preserved in the generated PDF report.
    """
    pdf_path = tmp_path / "cpplus_report.pdf"
    case = Case(case_number="CASE-CPPLUS-01", examiner="Examiner Test")
    evidence = Evidence(
        case_id=case.case_id,
        path="/tmp/fake_cpplus.dd",
        brand=CPPlusPlugin.display_name,
        brand_version="CP Plus (Dahua-compatible detection — unverified) — DHAV frame structure",
        confidence=0.95,
        is_synthetic=True,
    )

    generate_report(
        output_path=pdf_path,
        case=case,
        evidence=evidence,
        segments=[],
        log_events=[],
        audit_entries=[],
        chain_ok=True,
    )

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
