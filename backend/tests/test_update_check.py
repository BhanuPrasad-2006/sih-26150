"""
test_update_check.py — version comparison logic, and the /api/update/* endpoints.

The endpoints never make a real network call or spawn a real subprocess in tests: fetch_latest_version
and subprocess.Popen are both mocked, so this suite stays fast, deterministic and offline-safe.
"""

import unittest.mock as mock

from backend.update_check import is_newer, check_for_update


# ── Pure version comparison ─────────────────────────────────────────────────────

def test_is_newer_basic_cases():
    assert is_newer("1.0.1", "1.0.0") is True
    assert is_newer("1.1.0", "1.0.9") is True
    assert is_newer("2.0.0", "1.9.9") is True
    assert is_newer("1.0.0", "1.0.0") is False
    assert is_newer("1.0.0", "1.0.1") is False


def test_is_newer_handles_dev_suffix():
    # "1.0.0-dev" sorts before "1.0.0": a real release is newer than a dev build of the same number.
    assert is_newer("1.0.0", "1.0.0-dev") is True
    assert is_newer("1.0.0-dev", "1.0.0") is False


def test_is_newer_never_raises_on_garbage():
    assert is_newer("not-a-version", "1.0.0") in (True, False)
    assert is_newer("", "") is False


def test_check_for_update_reports_no_update_when_fetch_fails():
    with mock.patch("backend.update_check.fetch_latest_version", return_value=None):
        result = check_for_update("1.0.0")
    assert result == {"current": "1.0.0", "latest": None, "update_available": False}


def test_check_for_update_detects_a_newer_version():
    with mock.patch("backend.update_check.fetch_latest_version", return_value="1.2.0"):
        result = check_for_update("1.0.0")
    assert result["update_available"] is True
    assert result["latest"] == "1.2.0"


def test_check_for_update_no_update_when_already_current():
    with mock.patch("backend.update_check.fetch_latest_version", return_value="1.0.0"):
        result = check_for_update("1.0.0")
    assert result["update_available"] is False


# ── API endpoints ────────────────────────────────────────────────────────────────

def test_update_check_endpoint_needs_a_session(isolated_app):
    assert isolated_app.get("/api/update/check").status_code == 401


def test_update_check_endpoint_authenticated(auth_client):
    with mock.patch("backend.update_check.fetch_latest_version", return_value="99.0.0"):
        r = auth_client.get("/api/update/check")
    assert r.status_code == 200
    body = r.json()
    assert body["update_available"] is True
    assert body["latest"] == "99.0.0"


def test_apply_update_needs_a_session(isolated_app):
    assert isolated_app.post("/api/update/apply").status_code == 401


def test_apply_update_spawns_the_helper_without_a_real_subprocess(auth_client):
    import backend.main as m
    with mock.patch.object(m, "subprocess") as mock_subprocess, \
         mock.patch.object(m.Path, "exists", return_value=True):
        r = auth_client.post("/api/update/apply")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    mock_subprocess.Popen.assert_called_once()
    args = mock_subprocess.Popen.call_args[0][0]
    assert "apply_update.py" in args[-1]


def test_apply_update_refuses_when_not_a_git_checkout(auth_client):
    import backend.main as m
    with mock.patch.object(m.Path, "exists", return_value=False):
        r = auth_client.post("/api/update/apply")
    assert r.status_code == 400
    assert "git checkout" in r.json()["detail"]
