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

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from typing import Optional

import bcrypt

from backend import totp
from backend.secure_store import decrypt_text, encrypt_text


# ── Configuration ──────────────────────────────────────────────────────────────

def _timeout_minutes() -> int:
    """Session inactivity timeout in minutes (default 30, override via env)."""
    try:
        val = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
        return max(1, val)  # never less than 1 minute
    except (TypeError, ValueError):
        return 30


def _max_session_hours() -> float:
    """Absolute session lifetime regardless of activity (default 12 h, override via env)."""
    try:
        return max(0.25, float(os.environ.get("SESSION_MAX_HOURS", "12")))
    except (TypeError, ValueError):
        return 12.0


_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no 0/O/1/I
RECOVERY_CODE_COUNT = 10


def _norm_recovery(code: str) -> str:
    return re.sub(r"[\s-]", "", (code or "")).upper()


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

    def set_password_if_unset(self, plaintext: str) -> bool:
        """
        Atomically set the password only if none is set yet.

        Guards against a first-run TOCTOU race: two concurrent first-run
        setup requests both reading is_password_set() == False before either
        writes. The check and the write happen under the same lock here, so
        only the first caller ever succeeds.

        Returns True if this call set the password, False if a password was
        already set (no changes made).
        """
        with self._lock:
            if self._db.get_auth_value("password_hash") is not None:
                return False
            hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt())
            self._db.set_auth_value("password_hash", hashed.decode("utf-8"))
            return True

    def verify_password(self, plaintext: str) -> bool:
        """
        Constant-time bcrypt comparison.  Returns True on match, False otherwise.
        NEVER logs plaintext or any derivative of it.
        """
        stored = self._db.get_auth_value("password_hash")
        if not stored:
            return False
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored.encode("utf-8"))

    # ── Two-factor (TOTP) ──────────────────────────────────────────────────────

    def totp_enabled(self) -> bool:
        return bool(self._db.get_auth_value("totp_secret"))

    def begin_totp_enrollment(self) -> str:
        """Create a pending secret. It only becomes active after confirm_totp() sees a valid code."""
        with self._lock:
            if self.totp_enabled():
                raise ValueError("Two-factor authentication is already enabled.")
            secret = totp.generate_secret()
            self._db.set_auth_value("totp_pending", encrypt_text(secret))
            return secret

    def confirm_totp(self, code: str) -> Optional[list[str]]:
        """Activate two-factor. Returns the one-time recovery codes (shown once), or None if the code was wrong."""
        with self._lock:
            pending = self._db.get_auth_value("totp_pending")
            if not pending:
                return None
            secret = decrypt_text(pending)
            ok, counter = totp.verify(secret, code)
            if not ok:
                return None
            self._db.set_auth_value("totp_secret", encrypt_text(secret))
            self._db.set_auth_value("totp_last_counter", str(counter))
            self._db.set_auth_value("totp_pending", "")
            return self._store_new_recovery_codes()

    # ── Recovery codes (lost-phone fallback) ───────────────────────────────────

    def _store_new_recovery_codes(self) -> list[str]:
        """Caller holds self._lock. Only salted hashes are stored (encrypted); the plain codes are shown once."""
        codes = ["".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) + "-" +
                 "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) for _ in range(RECOVERY_CODE_COUNT)]
        entries = []
        for c in codes:
            salt = secrets.token_hex(8)
            entries.append({"s": salt, "h": hashlib.sha256((salt + _norm_recovery(c)).encode()).hexdigest()})
        self._db.set_auth_value("totp_recovery", encrypt_text(json.dumps(entries)))
        return codes

    def regenerate_recovery_codes(self) -> list[str]:
        with self._lock:
            if not self.totp_enabled():
                raise ValueError("Two-factor authentication is not enabled.")
            return self._store_new_recovery_codes()

    def recovery_codes_remaining(self) -> int:
        stored = self._db.get_auth_value("totp_recovery")
        return len(json.loads(decrypt_text(stored))) if stored else 0

    def verify_recovery_code(self, code: str) -> bool:
        """One-time use: a matching code is removed."""
        with self._lock:
            stored = self._db.get_auth_value("totp_recovery")
            if not stored:
                return False
            entries = json.loads(decrypt_text(stored))
            norm = _norm_recovery(code)
            for e in entries:
                if hmac.compare_digest(e["h"], hashlib.sha256((e["s"] + norm).encode()).hexdigest()):
                    entries.remove(e)
                    self._db.set_auth_value("totp_recovery", encrypt_text(json.dumps(entries)))
                    return True
            return False

    def verify_second_factor(self, code: str) -> bool:
        """A 6-digit authenticator code, or (when it does not look like one) a one-time recovery code."""
        c = (code or "").strip()
        if re.fullmatch(r"\d{3}\s?\d{3}", c):
            return self.verify_totp(c)
        return self.verify_recovery_code(c)

    def verify_totp(self, code: str) -> bool:
        """Verify a login code; a code (counter) can be used only once."""
        with self._lock:
            stored = self._db.get_auth_value("totp_secret")
            if not stored:
                return True                       # not enabled: nothing to check
            last = int(self._db.get_auth_value("totp_last_counter") or -1)
            ok, counter = totp.verify(decrypt_text(stored), code, last)
            if ok:
                self._db.set_auth_value("totp_last_counter", str(counter))
            return ok

    def disable_totp(self) -> None:
        with self._lock:
            for k in ("totp_secret", "totp_pending", "totp_last_counter", "totp_recovery"):
                self._db.set_auth_value(k, "")

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
            now = time.time()
            self._sessions[token] = {"last_activity": now, "created": now}
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
            now = time.time()
            if now - session["last_activity"] > _timeout_minutes() * 60:
                # Session has timed out — delete it
                del self._sessions[token]
                return False
            if now - session.get("created", now) > _max_session_hours() * 3600:
                # Absolute lifetime reached: even an active session must log in again
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

    def invalidate_other_sessions(self, keep_token: Optional[str]) -> int:
        """End every session except `keep_token` (after a security setting changes). Returns how many ended."""
        with self._lock:
            drop = [t for t in self._sessions if t != keep_token]
            for t in drop:
                del self._sessions[t]
            return len(drop)

    def session_count(self) -> int:
        """Return the number of active sessions (for diagnostics only)."""
        with self._lock:
            return len(self._sessions)
