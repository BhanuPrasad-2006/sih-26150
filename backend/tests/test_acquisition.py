"""
test_acquisition.py — Unit tests for acquisition.py
"""

import pytest
import os
import tempfile
from backend.acquisition import (
    load_disk_image,
    verify_disk_image_integrity,
    AcquisitionError
)

def test_load_disk_image_valid(dahua_img_path):
    mm, sha256_hash, md5_hash, size = load_disk_image(dahua_img_path)
    assert mm is not None
    assert len(sha256_hash) == 64
    assert len(md5_hash) == 32
    assert size > 0
    # Read-only check: attempting to write should raise TypeError or ValueError
    with pytest.raises((TypeError, ValueError)):
        mm[0:4] = b"TEST"
    mm.close()

def test_load_disk_image_nonexistent():
    with pytest.raises(AcquisitionError, match="File not found"):
        load_disk_image("nonexistent_file_12345.dd")


def test_load_disk_image_physical_drive_rejection():
    with pytest.raises(AcquisitionError, match="Physical disk paths are not supported"):
        load_disk_image(r"\\.\PhysicalDrive0")

def test_verify_disk_image_integrity(dahua_img_path):
    _, expected_sha256, _, _ = load_disk_image(dahua_img_path)
    match, current_sha256 = verify_disk_image_integrity(dahua_img_path, expected_sha256)
    assert match is True
    assert current_sha256 == expected_sha256

def test_verify_disk_image_integrity_mismatch(dahua_img_path):
    match, current_sha256 = verify_disk_image_integrity(dahua_img_path, "0" * 64)
    assert match is False

def test_onedrive_warning_and_configurable_case_dir(monkeypatch, temp_dir):
    from backend.database import warn_if_onedrive, get_case_dir

    # Test OneDrive warning detection
    onedrive_path = r"C:\Users\John\OneDrive\Desktop\sih_cases"
    warning = warn_if_onedrive(onedrive_path)
    assert warning is not None
    assert "WARNING" in warning
    assert "OneDrive" in warning

    # Test non-OneDrive path returns no warning
    clean_path = r"C:\sih_cases"
    assert warn_if_onedrive(clean_path) is None

    # Test environment variable override
    custom_dir = os.path.join(temp_dir, "custom_cases")
    monkeypatch.setenv("FORENSIC_CASE_DIR", custom_dir)
    assert str(get_case_dir()) == custom_dir

