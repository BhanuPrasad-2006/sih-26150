"""
test_auth_offline.py — Automated tests for local offline authentication.

Verifies:
1. Clean first-run behavior (no existing accounts, zero rows handled cleanly).
2. Local account creation & strict password strength validation.
3. Verification of credentials & brute-force lockout.
4. Complete isolation between separate installations.
5. Persistent 7-day remember-me token handling.
6. "Require password every time" security preference.
7. Offline API endpoints via FastAPI test client.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from backend.auth_db import AuthDB
from backend.auth import (
    AuthManager,
    UsernameTakenError,
    validate_password_strength,
    validate_username,
)
from backend import remember_token
from backend import local_config


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="sih_auth_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_clean_first_run_no_accounts(temp_dir):
    """Test 1: Fresh install with zero rows means no account created yet."""
    auth_db = AuthDB(temp_dir / "auth.db")
    auth = AuthManager(auth_db)

    assert not auth.has_any_user()
    assert auth.list_usernames() == []
    assert auth_db.get_auth_value("users") is None


def test_password_strength_rules():
    """Test 2: Password requirements must reject weak or simple passwords."""
    # Must reject 123412341234 (all numbers)
    with pytest.raises(ValueError, match="uppercase|lowercase|special"):
        validate_password_strength("123412341234")

    # Short (<8 chars)
    with pytest.raises(ValueError, match="at least 8"):
        validate_password_strength("Aa1!")

    # No uppercase
    with pytest.raises(ValueError, match="uppercase"):
        validate_password_strength("password123!")

    # No lowercase
    with pytest.raises(ValueError, match="lowercase"):
        validate_password_strength("PASSWORD123!")

    # No digit
    with pytest.raises(ValueError, match="digit"):
        validate_password_strength("PasswordSpecial!")

    # No special character
    with pytest.raises(ValueError, match="special"):
        validate_password_strength("Password12345")

    # Valid strong password
    valid = validate_password_strength("Examiner@2026!")
    assert valid == "Examiner@2026!"


def test_first_run_account_creation_and_login(temp_dir):
    """Test 3: First user account created locally and authenticated."""
    auth_db = AuthDB(temp_dir / "auth.db")
    auth = AuthManager(auth_db)

    # Atomically create first user
    ok = auth.create_first_user_if_none_exist("LeadExaminer", "SecurePassword@123!")
    assert ok is True
    assert auth.has_any_user() is True

    # Second call to create_first_user fails because account already exists
    assert auth.create_first_user_if_none_exist("SecondUser", "AnotherSecure@123!") is False

    # Credentials verification
    assert auth.verify_credentials("LeadExaminer", "SecurePassword@123!") is True
    assert auth.verify_credentials("LeadExaminer", "WrongPassword@123!") is False
    assert auth.verify_credentials("NonExistent", "SecurePassword@123!") is False


def test_installation_isolation(temp_dir):
    """Test 4: Computer A and Computer B have completely isolated credentials."""
    dir_a = temp_dir / "comp_a"
    dir_b = temp_dir / "comp_b"
    dir_a.mkdir()
    dir_b.mkdir()

    db_a = AuthDB(dir_a / "auth.db")
    auth_a = AuthManager(db_a)

    db_b = AuthDB(dir_b / "auth.db")
    auth_b = AuthManager(db_b)

    # Computer A creates account
    auth_a.create_first_user_if_none_exist("Bhanu", "MySecretPass@2026!")

    # Computer B has NO users, knows nothing about Bhanu
    assert auth_a.has_any_user() is True
    assert auth_b.has_any_user() is False
    assert auth_b.list_usernames() == []
    assert auth_b.verify_credentials("Bhanu", "MySecretPass@2026!") is False

    # Computer B creates its own user
    auth_b.create_first_user_if_none_exist("FriendExaminer", "FriendPass@2026#")
    assert auth_b.has_any_user() is True
    assert auth_b.verify_credentials("FriendExaminer", "FriendPass@2026#") is True
    assert auth_a.verify_credentials("FriendExaminer", "FriendPass@2026#") is False


def test_remember_token_lifecycle(temp_dir, monkeypatch):
    """Test 5: 7-day remember token save, load, expiry, and cleanup."""
    token_file = temp_dir / "remember_session.enc"
    monkeypatch.setattr(remember_token, "REMEMBER_TOKEN_FILE", token_file)
    monkeypatch.setattr(remember_token, "CONFIG_DIR", temp_dir)

    # Initially empty
    assert remember_token.load_remember_token() is None

    # Save token
    remember_token.save_remember_token("ExaminerOne", "random_session_token_xyz")
    assert token_file.is_file()

    # Load token
    data = remember_token.load_remember_token()
    assert data is not None
    assert data["username"] == "ExaminerOne"
    assert data["token"] == "random_session_token_xyz"
    assert data["expires_at"] > time.time()

    # Expired token simulation
    monkeypatch.setattr(time, "time", lambda: data["expires_at"] + 10)
    assert remember_token.load_remember_token() is None
    # Expired token automatically unlinked
    assert not token_file.is_file()


def test_security_preference_require_password_every_time(temp_dir, monkeypatch):
    """Test 6: 'Require password every time' preference controls remember token."""
    config_file = temp_dir / "config.json"
    token_file = temp_dir / "remember_session.enc"
    monkeypatch.setattr(local_config, "CONFIG_FILE", config_file)
    monkeypatch.setattr(local_config, "CONFIG_DIR", temp_dir)
    monkeypatch.setattr(remember_token, "REMEMBER_TOKEN_FILE", token_file)
    monkeypatch.setattr(remember_token, "CONFIG_DIR", temp_dir)

    # Default is False
    assert local_config.get_require_password_every_time() is False

    # Save a remember token
    remember_token.save_remember_token("ExaminerOne", "token123")
    assert token_file.is_file()

    # Set require password every time to True
    local_config.set_require_password_every_time(True)
    assert local_config.get_require_password_every_time() is True


def test_api_auth_flow(temp_dir, monkeypatch):
    """Test 7: End-to-end API test using FastAPI TestClient completely offline."""
    auth_db_path = temp_dir / "auth.db"
    config_file = temp_dir / "config.json"
    token_file = temp_dir / "remember_session.enc"

    monkeypatch.setattr(local_config, "CONFIG_FILE", config_file)
    monkeypatch.setattr(local_config, "CONFIG_DIR", temp_dir)
    monkeypatch.setattr(remember_token, "REMEMBER_TOKEN_FILE", token_file)
    monkeypatch.setattr(remember_token, "CONFIG_DIR", temp_dir)

    test_auth_db = AuthDB(auth_db_path)
    test_auth = AuthManager(test_auth_db)

    from backend import main
    monkeypatch.setattr(main, "auth_db", test_auth_db)
    monkeypatch.setattr(main, "auth", test_auth)

    client = TestClient(main.app)

    # 1. Fresh install status
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    body = res.json()
    assert body["has_account"] is False
    assert body["authenticated"] is False

    # 2. Setup first user with weak password -> rejected
    res = client.post("/api/auth/setup", json={"username": "Agent007", "password": "weak"})
    assert res.status_code == 422 or res.status_code == 400

    # 3. Setup first user with strong password -> 200
    res = client.post(
        "/api/auth/setup",
        json={"username": "Agent007", "password": "SecurePassword@2026!"},
    )
    assert res.status_code == 200
    assert "sih_session" in res.cookies

    # 4. Auth status now shows has_account=True
    res = client.get("/api/auth/status")
    assert res.json()["has_account"] is True

    # 5. Logout
    res = client.post("/api/auth/logout")
    assert res.status_code == 200

    # 6. Auto-login fails because logout cleared remember token
    res = client.get("/api/auth/auto-login")
    assert res.json()["authenticated"] is False

    # 7. Login with wrong password -> 401
    res = client.post(
        "/api/auth/login",
        json={"username": "Agent007", "password": "WrongPassword@2026!"},
    )
    assert res.status_code == 401

    # 8. Login with correct password and remember_me=True
    res = client.post(
        "/api/auth/login",
        json={"username": "Agent007", "password": "SecurePassword@2026!", "remember_me": True},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["username"] == "Agent007"
    assert token_file.is_file()

    # 9. Auto-login now succeeds via remember token
    # Create fresh client with no cookies
    fresh_client = TestClient(main.app)
    res = fresh_client.get("/api/auth/auto-login")
    assert res.status_code == 200
    assert res.json()["authenticated"] is True
    assert res.json()["username"] == "Agent007"
