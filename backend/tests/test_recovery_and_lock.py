"""Forgotten-password recovery keys, and certificate details locked after the first signed report."""

import re
import shutil
import tempfile
from pathlib import Path

import pytest

from backend import certificate_meta as cm
from backend.auth import AuthManager
from backend.auth_db import AuthDB
from backend.tests.conftest import _AUTH_TEST_PASSWORD, _AUTH_TEST_USERNAME

KEY_RE = re.compile(r"^[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}$")
NEW_PW = "Brand-New-Pass9"


@pytest.fixture
def manager():
    d = Path(tempfile.mkdtemp(prefix="sih_recovery_"))
    m = AuthManager(AuthDB(d / "auth.db"))
    m.create_user("examiner1", "Original-Pass1")
    yield m
    shutil.rmtree(d, ignore_errors=True)


# ── AuthManager ───────────────────────────────────────────────────────────────

def test_recovery_key_format_and_only_hash_is_stored(manager):
    key = manager.new_password_recovery_key("examiner1")
    assert KEY_RE.match(key)
    assert manager.has_password_recovery_key("examiner1")
    stored = manager._db.get_auth_value("users")
    assert key not in stored and key.replace("-", "") not in stored


def test_reset_with_key_changes_password_and_rotates_key(manager):
    key = manager.new_password_recovery_key("examiner1")
    new_key = manager.reset_password_with_recovery_key("examiner1", key.lower().replace("-", " "), NEW_PW)
    assert new_key and KEY_RE.match(new_key) and new_key != key
    assert manager.verify_credentials("examiner1", NEW_PW)
    assert not manager.verify_credentials("examiner1", "Original-Pass1")
    # the used key no longer works; the new one does
    assert manager.reset_password_with_recovery_key("examiner1", key, "Another-Pass2") is None
    assert manager.reset_password_with_recovery_key("examiner1", new_key, "Another-Pass2")


def test_wrong_key_or_unknown_user_fail_the_same_way(manager):
    manager.new_password_recovery_key("examiner1")
    assert manager.reset_password_with_recovery_key("examiner1", "AAAAA-BBBBB-CCCCC-DDDDD", NEW_PW) is None
    assert manager.reset_password_with_recovery_key("nobody", "AAAAA-BBBBB-CCCCC-DDDDD", NEW_PW) is None
    assert manager.verify_credentials("examiner1", "Original-Pass1")


def test_weak_new_password_is_rejected_before_the_key_is_checked(manager):
    key = manager.new_password_recovery_key("examiner1")
    with pytest.raises(ValueError):
        manager.reset_password_with_recovery_key("examiner1", key, "weak")
    assert manager.reset_password_with_recovery_key("examiner1", key, NEW_PW)   # key still valid


# ── API ───────────────────────────────────────────────────────────────────────

def test_setup_returns_a_recovery_key_that_resets_the_password(isolated_app):
    r = isolated_app.post("/api/auth/setup", json={"username": _AUTH_TEST_USERNAME, "password": _AUTH_TEST_PASSWORD})
    key = r.json()["recovery_key"]
    assert KEY_RE.match(key)
    isolated_app.post("/api/auth/logout")
    rec = isolated_app.post("/api/auth/recover", json={"username": _AUTH_TEST_USERNAME, "recovery_key": key, "new_password": NEW_PW})
    assert rec.status_code == 200 and KEY_RE.match(rec.json()["recovery_key"]) and rec.json()["recovery_key"] != key
    ok = isolated_app.post("/api/auth/login", json={"username": _AUTH_TEST_USERNAME, "password": NEW_PW})
    assert ok.status_code == 200 and ok.json()["ok"]


def test_recover_with_wrong_key_is_401_then_locks_out(isolated_app):
    isolated_app.post("/api/auth/setup", json={"username": _AUTH_TEST_USERNAME, "password": _AUTH_TEST_PASSWORD})
    isolated_app.post("/api/auth/logout")
    body = {"username": _AUTH_TEST_USERNAME, "recovery_key": "AAAAA-BBBBB-CCCCC-DDDDD", "new_password": NEW_PW}
    codes = [isolated_app.post("/api/auth/recover", json=body).status_code for _ in range(AuthManager.MAX_FAILURES + 1)]
    assert codes[0] == 401 and codes[-1] == 429
    assert "do not match" in isolated_app.post("/api/auth/recover", json=dict(body, username="ghost")).json()["detail"]


def test_regenerating_the_key_needs_the_current_password(auth_client):
    assert auth_client.get("/api/auth/recovery-key").json()["has_recovery_key"] is True
    assert auth_client.post("/api/auth/recovery-key", json={"password": "Wrong-Pass1"}).status_code == 401
    r = auth_client.post("/api/auth/recovery-key", json={"password": _AUTH_TEST_PASSWORD})
    assert r.status_code == 200 and KEY_RE.match(r.json()["recovery_key"])


# ── certificate lock ─────────────────────────────────────────────────────────

def _case(client, number):
    return client.post("/api/cases", json={"case_number": number, "examiner": "Tester", "notes": ""}).json()["case_id"]


def test_certificate_details_are_editable_until_locked_then_refused(auth_client):
    import backend.main as m
    cid = _case(auth_client, "LOCK-1")
    assert auth_client.get(f"/api/cases/{cid}/certificate").json()["locked_at"] is None
    assert auth_client.put(f"/api/cases/{cid}/certificate", json={"fir_number": "FIR 9/2026"}).status_code == 200
    assert cm.lock(m.db, cid, "2026-10-08T10:00:00+00:00") is True
    assert cm.lock(m.db, cid, "2026-10-09T10:00:00+00:00") is False          # first lock time is kept
    got = auth_client.get(f"/api/cases/{cid}/certificate").json()
    assert got["locked_at"].startswith("2026-10-08") and got["values"]["fir_number"] == "FIR 9/2026"
    refused = auth_client.put(f"/api/cases/{cid}/certificate", json={"fir_number": "CHANGED"})
    assert refused.status_code == 409 and "locked" in refused.json()["detail"]
    assert auth_client.get(f"/api/cases/{cid}/certificate").json()["values"]["fir_number"] == "FIR 9/2026"
    actions = [e["action"] for e in auth_client.get(f"/api/cases/{cid}/audit").json()["entries"]]
    assert "certificate_details_change_refused" in actions
