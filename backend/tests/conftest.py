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

AUTH FIXTURES
─────────────
isolated_app       — unauthenticated TestClient (for auth tests that need to call
                     login themselves, or to verify that unauthenticated access fails)
auth_client        — TestClient pre-authenticated with a test password.
                     Used by all non-auth tests so they keep passing after the
                     auth middleware was added.
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
from backend.auth import AuthManager
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


# ── Isolated (unauthenticated) app fixture ────────────────────────────────────

@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    """
    Yield a FastAPI TestClient backed by a fresh, empty Database in tmp_path.
    The client is NOT pre-authenticated — auth tests use this directly.

    Steps:
      1. Point FORENSIC_CASE_DIR at a new per-test subdirectory.
      2. Patch backend.main.db with a fresh Database() at that path.
      3. Create a fresh AuthManager pointing at the same db.
      4. Clear any in-memory state left from previous tests.
      5. Yield the TestClient.
      6. Restore the original db/auth after the test.
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

    fresh_auth = AuthManager(fresh_db)

    # Patch the module-level db and auth instances used by all routes
    monkeypatch.setattr(_main_module, "db", fresh_db)
    monkeypatch.setattr(_main_module, "auth", fresh_auth)

    # Clear in-memory per-case state
    _main_module._progress_queues.clear()
    _main_module._open_images.clear()
    _main_module._audit_logs.clear()
    _main_module._scan_tasks.clear()

    with TestClient(_main_module.app, raise_server_exceptions=True) as client:
        yield client

    # Restore env
    monkeypatch.setenv("FORENSIC_CASE_DIR", _SESSION_TMPDIR)


# ── Pre-authenticated app fixture ──────────────────────────────────────────────

_AUTH_TEST_PASSWORD = "TestPassword1234!"   # ≥12 chars, not the real examiner password


@pytest.fixture
def auth_client(isolated_app):
    """
    Yield a TestClient that is already authenticated.
    Used by all non-auth integration tests so they keep passing after auth was added.

    Sets up the password via /api/auth/setup, then logs in, so the session
    cookie is present in the client's cookie jar for subsequent requests.
    """
    # Set up password via setup endpoint (first-run flow)
    setup_res = isolated_app.post(
        "/api/auth/setup",
        json={"password": _AUTH_TEST_PASSWORD},
    )
    assert setup_res.status_code == 200, (
        f"auth_client fixture: setup failed: {setup_res.text}"
    )

    # The setup endpoint auto-creates a session cookie — client is now logged in
    assert "sih_session" in isolated_app.cookies, (
        "auth_client fixture: sih_session cookie not set after setup"
    )

    return isolated_app


# ── Legacy db_path fixture (kept for backward compatibility) ───────────────────

@pytest.fixture
def db_path(tmp_path, monkeypatch):
    test_case_dir = str(tmp_path / "cases")
    monkeypatch.setenv("FORENSIC_CASE_DIR", test_case_dir)
    db = Database()
    return db._path
