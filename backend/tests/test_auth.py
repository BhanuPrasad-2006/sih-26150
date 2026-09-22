"""
test_auth.py — Authentication and session management tests.

Tests:
  1. test_login_success                   — correct password → 200, session cookie set
  2. test_login_failure_wrong_password    — wrong password → 401, "Incorrect password."
  3. test_login_lockout_after_5_failures  — 5 bad attempts → 429 lockout response
  4. test_api_rejects_unauthenticated     — GET /api/cases without session → 401
  5. test_api_rejects_expired_session     — manually expire session → 401
  6. test_logout_invalidates_session      — login → logout → /api/cases → 401
"""

import time
import pytest
from fastapi.testclient import TestClient

import backend.main as _main_module
from backend.auth import AuthManager


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_PASSWORD = "SuperSecret1234"   # ≥12 chars


def _setup_password(client: TestClient) -> None:
    """Create the examiner password via the setup endpoint."""
    res = client.post("/api/auth/setup", json={"password": TEST_PASSWORD})
    assert res.status_code == 200, f"Setup failed: {res.text}"


def _login(client: TestClient, password: str = TEST_PASSWORD):
    """POST to /api/auth/login and return the response."""
    return client.post("/api/auth/login", json={"password": password})


# ── 1. Login success ──────────────────────────────────────────────────────────

def test_login_success(isolated_app):
    """
    Correct password after setup → HTTP 200, sih_session cookie present.
    """
    _setup_password(isolated_app)
    # Reset the auto-created session so we get a clean login test
    _main_module.auth.invalidate_session(
        isolated_app.cookies.get("sih_session")
    )
    isolated_app.cookies.clear()

    res = _login(isolated_app)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data.get("ok") is True, f"Expected ok=True, got: {data}"

    # The session cookie must be set
    assert "sih_session" in isolated_app.cookies, (
        "sih_session cookie was not set after successful login"
    )


# ── 2. Login failure — wrong password ─────────────────────────────────────────

def test_login_failure_wrong_password(isolated_app):
    """
    Wrong password → HTTP 401.
    Error message must be exactly "Incorrect password." — no other hints.
    The attempted password must NOT appear in the response.
    """
    _setup_password(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success()  # reset lockout counter

    res = _login(isolated_app, "WrongPassword999")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"

    data = res.json()
    detail = data.get("detail", "")
    assert "Incorrect password" in detail, (
        f"Error message should say 'Incorrect password.', got: {detail!r}"
    )
    # The wrong password must NOT appear in the response
    assert "WrongPassword999" not in res.text, (
        "The attempted password was leaked into the error response — this is a security bug."
    )


# ── 3. Lockout after 5 failures ───────────────────────────────────────────────

def test_login_lockout_after_5_failures(isolated_app):
    """
    5 consecutive wrong-password attempts → the 5th attempt triggers lockout.
    Subsequent attempt (6th) returns 429 with locked=True and retry_after.

    Verifies that lockout state persists across multiple requests (not just
    checked inline on each call).
    """
    _setup_password(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success()  # reset lockout counter

    # Make 5 bad attempts
    for i in range(5):
        res = _login(isolated_app, f"BadPassword{i}")
        # First 4 should be 401, 5th may be 429 depending on timing
        assert res.status_code in (401, 429), (
            f"Attempt {i+1}: expected 401 or 429, got {res.status_code}"
        )

    # The 6th attempt must always be locked out (429)
    res6 = _login(isolated_app, "AnyPassword")
    assert res6.status_code == 429, (
        f"6th attempt after 5 failures should be 429 (locked), got {res6.status_code}: {res6.text}"
    )
    data = res6.json()
    assert data.get("locked") is True, f"Expected locked=True, got: {data}"
    assert "retry_after" in data, f"Expected retry_after in response, got: {data}"
    assert data["retry_after"] > 0, f"retry_after should be >0, got: {data['retry_after']}"

    # Verify lockout persists: even with correct password, locked out
    res7 = _login(isolated_app, TEST_PASSWORD)
    assert res7.status_code == 429, (
        f"Lockout should persist even with correct password during lockout window. "
        f"Got {res7.status_code}"
    )


# ── 4. API rejects unauthenticated requests ───────────────────────────────────

def test_api_rejects_unauthenticated(isolated_app):
    """
    GET /api/cases without a session cookie must return HTTP 401.
    Verifies that AuthMiddleware is actually protecting routes.
    """
    _setup_password(isolated_app)
    # Ensure no cookies are sent
    isolated_app.cookies.clear()

    res = isolated_app.get("/api/cases")
    assert res.status_code == 401, (
        f"GET /api/cases without session cookie should return 401, got {res.status_code}: {res.text}"
    )
    data = res.json()
    assert "detail" in data, f"401 response should include 'detail', got: {data}"


# ── 5. API rejects expired sessions ──────────────────────────────────────────

def test_api_rejects_expired_session(isolated_app, monkeypatch):
    """
    A session whose last_activity is older than SESSION_TIMEOUT_MINUTES must be
    rejected with 401 on the next API call.

    We monkeypatch SESSION_TIMEOUT_MINUTES to 0 so we don't have to wait 30 min.
    """
    _setup_password(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success()

    # Login to get a valid session
    login_res = _login(isolated_app)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    assert "sih_session" in isolated_app.cookies

    # Force the session to appear expired by back-dating last_activity
    token = isolated_app.cookies.get("sih_session")
    with _main_module.auth._lock:
        if token in _main_module.auth._sessions:
            # Set last_activity to 31 minutes ago
            _main_module.auth._sessions[token]["last_activity"] = time.time() - (31 * 60)

    # Now any API call should fail with 401
    res = isolated_app.get("/api/cases")
    assert res.status_code == 401, (
        f"Expired session should return 401, got {res.status_code}: {res.text}"
    )


# ── 6. Logout invalidates session ─────────────────────────────────────────────

def test_logout_invalidates_session(isolated_app):
    """
    login → GET /api/cases (200) → logout → GET /api/cases (401).
    Verifies that logout actually removes the server-side session.
    """
    _setup_password(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success()

    # Step 1: login
    login_res = _login(isolated_app)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    assert "sih_session" in isolated_app.cookies

    # Step 2: verify access works
    cases_res = isolated_app.get("/api/cases")
    assert cases_res.status_code == 200, (
        f"Expected 200 on /api/cases after login, got {cases_res.status_code}"
    )

    # Step 3: logout
    logout_res = isolated_app.post("/api/auth/logout")
    assert logout_res.status_code == 200, f"Logout failed: {logout_res.text}"

    # Step 4: access should now be rejected
    # (cookie may still exist in client jar but server-side session is gone)
    res = isolated_app.get("/api/cases")
    assert res.status_code == 401, (
        f"After logout, /api/cases should return 401, got {res.status_code}: {res.text}"
    )
