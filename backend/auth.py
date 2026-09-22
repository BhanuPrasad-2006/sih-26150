"""
auth.py — Single-examiner authentication and session management.

Design principles (per project brief):
  • bcrypt for password storage — plaintext is NEVER stored, NEVER logged.
  • Sessions are in-memory dicts keyed by token.  Survives the process lifetime;
    on restart the examiner must log in again (acceptable for a single-examiner
    offline forensic tool).
  • Per-request session validation: every API call checks elapsed time against
    SESSION_TIMEOUT_MINUTES.  If expired → session is deleted and caller gets 401.
  • Per-account lockout: 5 consecutive failures → 60-second lockout tracked in a
    persistent counter dict (not per-request state), so lockout survives across
    the full 60 seconds.
  • Audit entries for login events log timestamp + attempt count ONLY.
    The attempted password is NEVER included — the audit log is cited as
    evidence-integrity proof and must not become a credential-leak vector.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Optional

import bcrypt


# ── Configuration ──────────────────────────────────────────────────────────────

def _timeout_minutes() -> int:
    """Session inactivity timeout in minutes (default 30, override via env)."""
    try:
        val = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
        return max(1, val)  # never less than 1 minute
    except (TypeError, ValueError):
        return 30


# ── Auth state ─────────────────────────────────────────────────────────────────

class AuthManager:
    """
    Owns all authentication and session state for the single-examiner tool.

    Thread-safe — all mutable state is protected by self._lock.
    Instantiate once at app startup and reuse across all requests.
    """

    # Lockout constants
    MAX_FAILURES:    int = 5
    LOCKOUT_SECONDS: int = 60

    def __init__(self, db) -> None:
        """
        Args:
            db: a backend.database.Database instance, used to persist the
                password hash across restarts.
        """
        self._db = db
        self._lock = threading.Lock()

        # { token: {"last_activity": float_timestamp} }
        self._sessions: dict[str, dict] = {}

        # Per-account lockout state (single-examiner → effectively global)
        self._failure_count:   int   = 0
        self._lockout_until:   float = 0.0   # epoch seconds; 0 = not locked out

    # ── Password management ────────────────────────────────────────────────────

    def is_password_set(self) -> bool:
        """Return True if a password hash has been stored in the database."""
        return self._db.get_auth_value("password_hash") is not None

    def set_password(self, plaintext: str) -> None:
        """
        Hash plaintext with bcrypt and persist the hash.
        plaintext is NEVER logged or stored as-is.
        """
        # bcrypt.gensalt() uses a cost factor of 12 by default — appropriate for
        # an offline single-user tool where login is infrequent.
        hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt())
        self._db.set_auth_value("password_hash", hashed.decode("utf-8"))

    def verify_password(self, plaintext: str) -> bool:
        """
        Constant-time bcrypt comparison.  Returns True on match, False otherwise.
        NEVER logs plaintext or any derivative of it.
        """
        stored = self._db.get_auth_value("password_hash")
        if not stored:
            return False
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored.encode("utf-8"))

    # ── Lockout management ─────────────────────────────────────────────────────

    def is_locked_out(self) -> tuple[bool, int]:
        """
        Return (locked_out: bool, seconds_remaining: int).
        Lockout expires automatically when time passes.
        """
        with self._lock:
            if time.time() < self._lockout_until:
                remaining = int(self._lockout_until - time.time())
                return True, remaining
            return False, 0

    def record_failure(self) -> tuple[int, bool]:
        """
        Record one failed login attempt.
        Returns (failure_count, just_locked_out).
        just_locked_out is True when this failure triggered the lockout.
        """
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.MAX_FAILURES and self._lockout_until <= time.time():
                self._lockout_until = time.time() + self.LOCKOUT_SECONDS
                return self._failure_count, True
            return self._failure_count, False

    def record_success(self) -> None:
        """Reset failure counter on successful login."""
        with self._lock:
            self._failure_count = 0
            self._lockout_until = 0.0

    # ── Session management ─────────────────────────────────────────────────────

    def create_session(self) -> str:
        """
        Generate a cryptographically random session token, store it with the
        current timestamp, and return the token string.
        """
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = {"last_activity": time.time()}
        return token

    def validate_session(self, token: Optional[str]) -> bool:
        """
        Check whether token corresponds to a live, non-expired session.

        This performs the ACTIVE enforcement of session timeout:
          elapsed = now - last_activity
          if elapsed > SESSION_TIMEOUT_MINUTES * 60 → delete session, return False

        Must be called on every authenticated request (enforced by middleware).
        """
        if not token:
            return False
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return False
            elapsed = time.time() - session["last_activity"]
            if elapsed > _timeout_minutes() * 60:
                # Session has timed out — delete it
                del self._sessions[token]
                return False
            return True

    def touch_session(self, token: str) -> None:
        """
        Update last_activity timestamp on every valid request to keep the
        session alive while the examiner is actively using the tool.
        """
        with self._lock:
            if token in self._sessions:
                self._sessions[token]["last_activity"] = time.time()

    def invalidate_session(self, token: Optional[str]) -> None:
        """Delete a session (logout)."""
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def session_count(self) -> int:
        """Return the number of active sessions (for diagnostics only)."""
        with self._lock:
            return len(self._sessions)
