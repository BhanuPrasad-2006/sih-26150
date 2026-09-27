"""
test_first_run_wizard.py — the first-run wizard's backend: /api/version, /api/setup/*.

The wizard runs before any password exists, so all three endpoints must be reachable with no
session cookie at all (they are listed in _AUTH_EXEMPT_PATHS in main.py).
"""

import os
import shutil
import tempfile

import pytest


def test_version_endpoint_is_unauthenticated_and_matches_the_version_file(isolated_app):
    from backend.local_config import get_version
    r = isolated_app.get("/api/version")
    assert r.status_code == 200
    assert r.json()["version"] == get_version()
    assert r.json()["version"] != ""


def test_first_run_status_before_setup(isolated_app):
    r = isolated_app.get("/api/setup/first-run-status")
    assert r.status_code == 200
    body = r.json()
    assert body["complete"] is False
    assert body["terms_version"]
    assert body["default_case_dir"]


def test_first_run_complete_requires_accepting_terms(isolated_app, temp_dir):
    target = os.path.join(temp_dir, "cases")
    r = isolated_app.post("/api/setup/first-run-complete", json={"case_dir": target, "accept_terms": False})
    assert r.status_code == 400
    assert "accept" in r.json()["detail"].lower()
    assert not os.path.isdir(target)


def test_first_run_complete_creates_the_folder_and_persists(isolated_app, temp_dir):
    target = os.path.join(temp_dir, "my_cases")
    r = isolated_app.post("/api/setup/first-run-complete", json={"case_dir": target, "accept_terms": True})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert os.path.isdir(target)

    status = isolated_app.get("/api/setup/first-run-status").json()
    assert status["complete"] is True


def test_first_run_complete_rejects_an_unusable_path(isolated_app):
    # A file (not a directory) can never be turned into a case folder.
    fd, path = tempfile.mkstemp()
    os.close(fd)
    try:
        r = isolated_app.post("/api/setup/first-run-complete", json={"case_dir": path, "accept_terms": True})
        assert r.status_code == 400
    finally:
        os.remove(path)


def test_first_run_complete_is_reachable_with_no_session_cookie(isolated_app, temp_dir):
    """The whole point of this endpoint: it must work before any password/session exists."""
    target = os.path.join(temp_dir, "no_session_cases")
    r = isolated_app.post("/api/setup/first-run-complete", json={"case_dir": target, "accept_terms": True})
    assert r.status_code == 200
