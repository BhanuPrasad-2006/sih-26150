"""
test_evidence_formats.py — Unit tests for extended forensic disk image formats,
path sanitization (Windows quote stripping), and targeted evidence scanning.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import (
    _ALLOWED_EVIDENCE_EXTS,
    LoadEvidenceRequest,
    app,
    auth,
    auth_db,
    db,
)


@pytest.fixture
def api_client(tmp_path: Path):
    """Provide an authenticated TestClient with an isolated test database."""
    # Ensure fresh auth state
    test_user = "test_examiner"
    test_pw = "ExamPass@2026!"
    if not auth.has_any_user():
        auth.create_first_user_if_none_exist(test_user, test_pw)

    client = TestClient(app)
    res = client.post("/api/auth/login", json={"username": test_user, "password": test_pw})
    assert res.status_code == 200
    return client


def test_allowed_evidence_extensions_comprehensive():
    """Verify that all standard forensic, raw, and container extensions are permitted."""
    expected = {
        ".dd", ".img", ".raw", ".bin", ".001", ".iso",
        ".vmdk", ".vhd", ".vhdx", ".e01", ".ex01", ".aff", ".aff4", ".qcow2",
        "",  # Extensionless raw image files
    }
    for ext in expected:
        assert ext in _ALLOWED_EVIDENCE_EXTS, f"Extension {ext} should be in _ALLOWED_EVIDENCE_EXTS"


def test_path_sanitization_and_quote_stripping(tmp_path: Path):
    """Ensure Windows 'Copy as path' quotes are cleanly stripped."""
    test_file = tmp_path / "sample_evidence.dd"
    test_file.write_bytes(b"FORENSIC_RAW_BYTES" * 32)

    quoted_windows_path = f'"{test_file}"'
    req = LoadEvidenceRequest(path=quoted_windows_path)
    assert req.path == str(test_file)
    assert not req.path.startswith('"')
    assert not req.path.endswith('"')

    single_quoted_path = f"'{test_file}'"
    req2 = LoadEvidenceRequest(path=single_quoted_path)
    assert req2.path == str(test_file)


def test_split_raw_001_extension_allowed(tmp_path: Path):
    """Verify that split raw images (.001) are accepted by validator."""
    test_file = tmp_path / "forensic_image.001"
    test_file.write_bytes(b"SPLIT_RAW_DATA" * 16)

    req = LoadEvidenceRequest(path=str(test_file))
    assert req.path == str(test_file)


def test_extensionless_raw_file_allowed(tmp_path: Path):
    """Verify that raw files without an extension (e.g. sda, disk) are accepted."""
    test_file = tmp_path / "sdc_raw_drive"
    test_file.write_bytes(b"RAW_DATA_NO_EXT" * 16)

    req = LoadEvidenceRequest(path=str(test_file))
    assert req.path == str(test_file)


def test_desktop_bridge_pick_file():
    """Verify that _DesktopBridge has pick_file and pick_folder methods."""
    from backend.desktop_app import _DesktopBridge
    bridge = _DesktopBridge()
    assert hasattr(bridge, "pick_file"), "_DesktopBridge must define pick_file"
    assert hasattr(bridge, "pick_folder"), "_DesktopBridge must define pick_folder"


def test_targeted_evidence_scan(api_client: TestClient, tmp_path: Path):
    """Test that POST /api/cases/{case_id}/scan accepts and targets a specific evidence_id."""
    # 1. Create a test case
    case_res = api_client.post("/api/cases", json={
        "case_number": "FORMAT-TEST-001",
        "examiner": "test_examiner",
        "priority": "LOW",
    })
    assert case_res.status_code == 200
    case_id = case_res.json()["case_id"]

    # 2. Add two evidence images
    img1 = tmp_path / "img1.001"
    img1.write_bytes(b"DATA1" * 64)
    img2 = tmp_path / "img2.raw"
    img2.write_bytes(b"DATA2" * 64)

    ev1_res = api_client.post(f"/api/cases/{case_id}/evidence", json={"path": str(img1)})
    assert ev1_res.status_code == 200
    ev1_id = ev1_res.json()["evidence_id"]

    ev2_res = api_client.post(f"/api/cases/{case_id}/evidence", json={"path": str(img2)})
    assert ev2_res.status_code == 200
    ev2_id = ev2_res.json()["evidence_id"]

    # 3. Request scan targeting specifically ev1_id
    scan_res = api_client.post(f"/api/cases/{case_id}/scan?evidence_id={ev1_id}")
    assert scan_res.status_code == 200
    assert scan_res.json()["status"] == "started"
    assert scan_res.json()["evidence_id"] == ev1_id
