"""
test_auth.py — Multi-examiner authentication and session management tests.

Tests:
  1. test_login_success                        — correct username+password → 200, session cookie set
  2. test_login_failure_wrong_password          — wrong password → 401, generic message
  3. test_login_failure_unknown_username        — unknown username → same 401, same message
  4. test_login_lockout_after_5_failures        — 5 bad attempts on ONE account → 429 lockout
  5. test_lockout_is_per_account_not_global     — a locked-out account does not block a different one
  6. test_api_rejects_unauthenticated           — GET /api/cases without session → 401
  7. test_api_rejects_expired_session           — manually expire session → 401
  8. test_logout_invalidates_session            — login → logout → /api/cases → 401
  9. test_signup_requires_an_existing_session   — /api/auth/signup is not exempt from auth
 10. test_signup_adds_a_second_examiner         — a logged-in examiner can add another
 11. test_signup_rejects_a_taken_username       — case-insensitive uniqueness
 12. test_second_examiner_has_their_own_password — accounts are fully independent
 13. test_setup_refuses_once_an_account_exists  — first-run bootstrap is one-time only
 14. test_weak_passwords_are_rejected           — strong-password rule enforced at signup/setup
 15. test_username_validation                   — length/character rules enforced
"""

import time
import pytest
from fastapi.testclient import TestClient

import backend.main as _main_module
from backend.auth import AuthManager
from backend.tests.conftest import _AUTH_TEST_USERNAME, _AUTH_TEST_PASSWORD


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USERNAME = _AUTH_TEST_USERNAME
TEST_PASSWORD = _AUTH_TEST_PASSWORD   # meets the strong-password rule


def _setup_account(client: TestClient, username: str = TEST_USERNAME, password: str = TEST_PASSWORD) -> None:
    """Create the first examiner account via the setup endpoint."""
    res = client.post("/api/auth/setup", json={"username": username, "password": password})
    assert res.status_code == 200, f"Setup failed: {res.text}"


def _login(client: TestClient, username: str = TEST_USERNAME, password: str = TEST_PASSWORD):
    """POST to /api/auth/login and return the response."""
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ── 1. Login success ──────────────────────────────────────────────────────────

def test_login_success(isolated_app):
    """Correct username+password after setup → HTTP 200, sih_session cookie present."""
    _setup_account(isolated_app)
    # Reset the auto-created session so we get a clean login test
    _main_module.auth.invalidate_session(isolated_app.cookies.get("sih_session"))
    isolated_app.cookies.clear()

    res = _login(isolated_app)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data.get("ok") is True, f"Expected ok=True, got: {data}"
    assert data.get("username") == TEST_USERNAME

    assert "sih_session" in isolated_app.cookies, (
        "sih_session cookie was not set after successful login"
    )


# ── 2/3. Login failure ────────────────────────────────────────────────────────

def test_login_failure_wrong_password(isolated_app):
    """Wrong password → HTTP 401. The attempted password must NOT appear in the response."""
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success(TEST_USERNAME)  # reset lockout counter

    res = _login(isolated_app, password="WrongPassword999!")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    detail = res.json().get("detail", "")
    assert "ncorrect" in detail
    assert "WrongPassword999" not in res.text, (
        "The attempted password was leaked into the error response — this is a security bug."
    )


def test_login_failure_unknown_username(isolated_app):
    """An unknown username must fail with the exact same status and message as a wrong password —
    never revealing whether an account exists."""
    _setup_account(isolated_app)
    isolated_app.cookies.clear()

    wrong_pw = _login(isolated_app, password="WrongPassword999!")
    unknown_user = _login(isolated_app, username="no_such_examiner", password=TEST_PASSWORD)
    assert wrong_pw.status_code == unknown_user.status_code == 401
    assert wrong_pw.json()["detail"] == unknown_user.json()["detail"]


# ── 4/5. Lockout ───────────────────────────────────────────────────────────────

def test_login_lockout_after_5_failures(isolated_app):
    """5 consecutive wrong-password attempts on ONE account → the 5th triggers lockout."""
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success(TEST_USERNAME)

    for i in range(5):
        res = _login(isolated_app, password=f"BadPassword{i}!")
        assert res.status_code in (401, 429), f"Attempt {i+1}: expected 401 or 429, got {res.status_code}"

    res6 = _login(isolated_app, password="AnyPassword!")
    assert res6.status_code == 429, f"6th attempt should be 429 (locked), got {res6.status_code}: {res6.text}"
    data = res6.json()
    assert data.get("locked") is True
    assert data.get("retry_after", 0) > 0

    res7 = _login(isolated_app)  # correct password, still locked
    assert res7.status_code == 429, "Lockout should persist even with the correct password during the lockout window."


def test_lockout_is_per_account_not_global(isolated_app):
    """Locking out one examiner's account must never block a different examiner from logging in."""
    _setup_account(isolated_app, username=TEST_USERNAME)
    isolated_app.cookies.clear()
    second_user, second_pw = "second_examiner", "AnotherStrong1!"
    assert isolated_app.post("/api/auth/setup", json={"username": second_user, "password": second_pw}).status_code == 400
    # (setup only works once — add the 2nd account the real way, logged in as the first)
    _login(isolated_app)
    assert isolated_app.post("/api/auth/signup", json={"username": second_user, "password": second_pw}).status_code == 200
    isolated_app.post("/api/auth/logout")
    isolated_app.cookies.clear()

    for _ in range(5):
        _login(isolated_app, username=TEST_USERNAME, password="wrong-wrong-wrong!")
    assert _login(isolated_app, username=TEST_USERNAME).status_code == 429   # first account: locked

    ok = _login(isolated_app, username=second_user, password=second_pw)
    assert ok.status_code == 200, "A different examiner's account must be unaffected by another's lockout."


# ── 6. API rejects unauthenticated requests ───────────────────────────────────

def test_api_rejects_unauthenticated(isolated_app):
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    res = isolated_app.get("/api/cases")
    assert res.status_code == 401
    assert "detail" in res.json()


# ── 7. API rejects expired sessions ──────────────────────────────────────────

def test_api_rejects_expired_session(isolated_app, monkeypatch):
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success(TEST_USERNAME)

    login_res = _login(isolated_app)
    assert login_res.status_code == 200
    assert "sih_session" in isolated_app.cookies

    token = isolated_app.cookies.get("sih_session")
    with _main_module.auth._lock:
        if token in _main_module.auth._sessions:
            _main_module.auth._sessions[token]["last_activity"] = time.time() - (31 * 60)

    res = isolated_app.get("/api/cases")
    assert res.status_code == 401


# ── 8. Logout invalidates session ─────────────────────────────────────────────

def test_logout_invalidates_session(isolated_app):
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    _main_module.auth.record_success(TEST_USERNAME)

    login_res = _login(isolated_app)
    assert login_res.status_code == 200
    assert isolated_app.get("/api/cases").status_code == 200

    assert isolated_app.post("/api/auth/logout").status_code == 200
    assert isolated_app.get("/api/cases").status_code == 401


# ── 9-12. Multi-user: signup, uniqueness, independence ────────────────────────

def test_signup_requires_an_existing_session(isolated_app):
    """/api/auth/signup is NOT exempt from AuthMiddleware — a stranger cannot mint themselves
    an account just because the server is reachable."""
    _setup_account(isolated_app)
    isolated_app.cookies.clear()
    res = isolated_app.post("/api/auth/signup", json={"username": "intruder", "password": "SomethingStrong1!"})
    assert res.status_code == 401


def test_signup_adds_a_second_examiner(auth_client):
    res = auth_client.post("/api/auth/signup", json={"username": "second_examiner_2", "password": "AnotherStrong2!"})
    assert res.status_code == 200, res.text
    usernames = auth_client.get("/api/auth/examiners").json()["usernames"]
    assert TEST_USERNAME in usernames and "second_examiner_2" in usernames


def test_signup_rejects_a_taken_username(auth_client):
    assert auth_client.post("/api/auth/signup", json={"username": "dup_user", "password": "AnotherStrong2!"}).status_code == 200
    # Case-insensitive collision
    dup = auth_client.post("/api/auth/signup", json={"username": "DUP_USER", "password": "YetAnother3!"})
    assert dup.status_code == 409


def test_second_examiner_has_their_own_password(auth_client):
    """Two accounts are fully independent: a wrong password for one never authenticates the other,
    and each keeps their own lockout counter."""
    assert auth_client.post("/api/auth/signup", json={"username": "indep_examiner", "password": "IndepStrong1!"}).status_code == 200
    auth_client.post("/api/auth/logout")
    isolated_client = auth_client
    isolated_client.cookies.clear()

    wrong = isolated_client.post("/api/auth/login", json={"username": "indep_examiner", "password": TEST_PASSWORD})
    assert wrong.status_code == 401
    right = isolated_client.post("/api/auth/login", json={"username": "indep_examiner", "password": "IndepStrong1!"})
    assert right.status_code == 200


# ── 13. First-run bootstrap is one-time only ──────────────────────────────────

def test_setup_refuses_once_an_account_exists(isolated_app):
    _setup_account(isolated_app)
    again = isolated_app.post("/api/auth/setup", json={"username": "someone_else", "password": "SomethingStrong1!"})
    assert again.status_code == 400


# ── 14/15. Validation rules ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_password,why", [
    ("short1A!", "too short"),
    ("alllowercase123!", "no uppercase"),
    ("ALLUPPERCASE123!", "no lowercase"),
    ("NoDigitsHere!!", "no digit"),
    ("NoSpecialChars123", "no special character"),
])
def test_weak_passwords_are_rejected(isolated_app, bad_password, why):
    res = isolated_app.post("/api/auth/setup", json={"username": "weakpw_test", "password": bad_password})
    assert res.status_code == 422, f"{why}: expected a validation error for {bad_password!r}"


@pytest.mark.parametrize("bad_username", ["ab", "a" * 40, "-startshyphen", "endshyphen-", "bad!char"])
def test_username_validation(isolated_app, bad_username):
    res = isolated_app.post("/api/auth/setup", json={"username": bad_username, "password": TEST_PASSWORD})
    assert res.status_code == 422, f"expected a validation error for username {bad_username!r}"
