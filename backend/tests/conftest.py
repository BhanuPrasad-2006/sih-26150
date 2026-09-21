"""
backend/tests/conftest.py — Shared test fixtures for pytest.

ISOLATION GUARANTEE
───────────────────
The FORENSIC_CASE_DIR environment variable is set to a fresh temporary directory
*before* any backend module is imported.  This is done at module-level (not inside
a fixture) so that the module-level ``db = Database()`` in main.py is never reached
before the env override is applied.

A session-scoped safety fixture ``assert_no_real_db`` verifies that the Database
path used during the test run does NOT point at the real production folder
(C:/sih_cases or ~/sih_cases).  Any test that accidentally imports the real DB will
fail fast with a clear message rather than silently polluting production data.
"""

import os
import tempfile

# ── Override FORENSIC_CASE_DIR BEFORE any backend import ─────────────────────
# conftest.py is the first file loaded by pytest in this package.
# By setting the env var here at module scope, Database() in main.py will use
# our temp directory even if main.py is imported at collection time.
_SESSION_TMPDIR = tempfile.mkdtemp(prefix="sih_test_")
os.environ["FORENSIC_CASE_DIR"] = _SESSION_TMPDIR

# ── Now it is safe to import backend modules ──────────────────────────────────
import pytest
import asyncio
import unittest.mock as mock
from pathlib import Path

from backend.test_images.gen_test_image import (
    generate_dahua_image,
    generate_hikvision_image,
    generate_foreign_image,
)
from backend.database import Database
import backend.main as _main_module


# ── Safety assertion ──────────────────────────────────────────────────────────

_REAL_CASE_DIRS = {
    Path("C:/sih_cases").resolve(),
    Path("c:/sih_cases").resolve(),
    (Path.home() / "sih_cases").resolve(),
}


@pytest.fixture(scope="session", autouse=True)
def assert_no_real_db():
    """Fail the entire test run if any database resolves to the production folder."""
    db_path = Path(_main_module.db._path).resolve().parent
    assert db_path not in _REAL_CASE_DIRS, (
        f"\n\n[SAFETY ABORT] Tests are about to write to the real case database at:\n"
        f"  {db_path}\n\n"
        f"Set FORENSIC_CASE_DIR to a temp directory before importing backend.main.\n"
        f"Check conftest.py for the isolation setup."
    )
    yield
    # Teardown: nothing — the temp dir is cleaned up at process exit via atexit
    # (mkdtemp dirs survive the session so test artifacts can be inspected if needed)


# ── Session-scoped temp directory ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def temp_dir():
    """Return the session temp directory (already set as FORENSIC_CASE_DIR)."""
    return _SESSION_TMPDIR


# ── Synthetic disk images ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def dahua_img_path(temp_dir):
    path = os.path.join(temp_dir, "synthetic_dahua.dd")
    if not os.path.exists(path):
        generate_dahua_image(path, num_frames=20, include_gap=True)
    return path


@pytest.fixture(scope="session")
def hikvision_img_path(temp_dir):
    path = os.path.join(temp_dir, "synthetic_hikvision.dd")
    if not os.path.exists(path):
        generate_hikvision_image(path)
    return path


@pytest.fixture(scope="session")
def foreign_img_path(temp_dir):
    path = os.path.join(temp_dir, "synthetic_ext4.dd")
    if not os.path.exists(path):
        generate_foreign_image(path, fs_type="ext4")
    return path


# ── Isolated app fixture ───────────────────────────────────────────────────────

@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    """
    Yield a FastAPI TestClient backed by a fresh, empty Database in tmp_path.

    Steps:
      1. Point FORENSIC_CASE_DIR at a new per-test subdirectory.
      2. Patch backend.main.db with a fresh Database() at that path.
      3. Clear any in-memory state left from previous tests.
      4. Yield the TestClient.
      5. Restore the original db after the test.
    """
    from fastapi.testclient import TestClient

    test_case_dir = str(tmp_path / "cases")
    monkeypatch.setenv("FORENSIC_CASE_DIR", test_case_dir)

    fresh_db = Database()

    # Safety: verify the fresh_db is NOT in the real directory
    fresh_db_parent = Path(fresh_db._path).resolve().parent
    assert fresh_db_parent not in _REAL_CASE_DIRS, (
        f"isolated_app fixture created a DB at the real case dir: {fresh_db_parent}"
    )

    # Patch the module-level db instance used by all routes
    monkeypatch.setattr(_main_module, "db", fresh_db)
    # Clear in-memory per-case state
    _main_module._progress_queues.clear()
    _main_module._open_images.clear()
    _main_module._audit_logs.clear()
    _main_module._scan_tasks.clear()

    with TestClient(_main_module.app) as client:
        yield client

    # Restore env
    monkeypatch.setenv("FORENSIC_CASE_DIR", _SESSION_TMPDIR)


# ── Legacy db_path fixture (kept for backward compatibility) ───────────────────

@pytest.fixture
def db_path(tmp_path, monkeypatch):
    test_case_dir = str(tmp_path / "cases")
    monkeypatch.setenv("FORENSIC_CASE_DIR", test_case_dir)
    db = Database()
    return db._path
