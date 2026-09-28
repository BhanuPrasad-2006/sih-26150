"""
auth.py — Multi-examiner authentication and session management.

Design principles (per project brief, extended to support named accounts):
  • bcrypt for password storage — plaintext is NEVER stored, NEVER logged.
  • Every examiner has their own username, password, 2FA enrollment, recovery codes, and
    login-lockout counter. There is no cross-account privilege model (no admin role, no per-case
    permissions) — every logged-in examiner can see every case, exactly as before this change.
    "Multi-user" here means named, separate credentials and audit attribution, not multi-tenancy.
  • All examiner records live in ONE JSON blob under auth_state["users"] (keyed by the database's
    existing generic get_auth_value/set_auth_value, identical on SQLite and Postgres) rather than
    a new SQL table — this avoids a schema migration on either backend.
  • Sessions are in-memory dicts keyed by token, each remembering which username it belongs to.
    Survives the process lifetime; on restart every examiner must log in again (acceptable for an
    offline forensic tool).
  • Per-request session validation: every API call checks elapsed time against
    SESSION_TIMEOUT_MINUTES. If expired -> session is deleted and caller gets 401.
  • Per-account lockout: 5 consecutive failures for THAT username -> 60-second lockout, persisted
    in the database (not just in memory), so restarting the server does not reset it, and one
    examiner's lockout never affects another's.
  • Audit entries for login events log timestamp + attempt count + username ONLY.
    The attempted password is NEVER included — the audit log is cited as evidence-integrity proof
    and must not become a credential-leak vector.
  • Forgotten password: there is no email/SMS on an offline tool, so recovery is a CLI script
    (tools/reset_user_password.py) run with terminal access to the machine — the same trust model
    as most self-hosted server software's "manage.py resetpassword" equivalents.
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

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{1,30}[A-Za-z0-9]$|^[A-Za-z0-9]{2,32}$")

# Strong-password rule, shared by signup, "add another examiner", and the CLI reset tool, so the
# requirement can never drift between the three entry points.
MIN_PASSWORD_LENGTH = 12


def _norm_recovery(code: str) -> str:
    return re.sub(r"[\s-]", "", (code or "")).upper()


def validate_username(username: str) -> str:
    """Raises ValueError with a user-facing message; otherwise returns the trimmed username."""
    u = (username or "").strip()
    if not (3 <= len(u) <= 32):
        raise ValueError("Username must be 3-32 characters long.")
    if not _USERNAME_RE.match(u):
        raise ValueError("Username may contain letters, numbers, spaces, dots, underscores and "
                          "hyphens only, and must start and end with a letter or number.")
    return u


def validate_password_strength(password: str) -> str:
    """
    Raises ValueError with a user-facing message; otherwise returns the password unchanged.
    Length alone (the old rule) is no longer considered "strong": also require at least one
    uppercase letter, one lowercase letter, one digit, and one non-alphanumeric character.
    """
    pw = password or ""
    if len(pw) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if not re.search(r"[A-Z]", pw):
        raise ValueError("Password must include at least one uppercase letter.")
    if not re.search(r"[a-z]", pw):
        raise ValueError("Password must include at least one lowercase letter.")
    if not re.search(r"\d", pw):
        raise ValueError("Password must include at least one digit.")
    if not re.search(r"[^A-Za-z0-9]", pw):
        raise ValueError("Password must include at least one special character (e.g. ! @ # $ %).")
    return pw


class UsernameTakenError(ValueError):
    pass


# ── Auth state ─────────────────────────────────────────────────────────────────

class AuthManager:
    """
    Owns authentication and session state for every examiner account on this installation.

    Thread-safe — all mutable state is protected by self._lock.
    Instantiate once at app startup and reuse across all requests.
    """

    # Lockout constants
    MAX_FAILURES:    int = 5
    LOCKOUT_SECONDS: int = 60

    def __init__(self, db) -> None:
        """
        Args:
            db: a backend.database.Database (or PostgresDatabase) instance, used to persist
                every examiner's record across restarts.
        """
        self._db = db
        self._lock = threading.Lock()

        # { token: {"username": str, "last_activity": float_timestamp, "created": float} }
        self._sessions: dict[str, dict] = {}

    # ── User record storage ───────────────────────────────────────────────────
    # Caller must hold self._lock for any of the _users_* helpers below.

    def _load_users(self) -> dict:
        raw = self._db.get_auth_value("users")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    def _save_users(self, users: dict) -> None:
        self._db.set_auth_value("users", json.dumps(users))

    @staticmethod
    def _key(username: str) -> str:
        return username.strip().lower()

    def _new_user_record(self, username: str, password_hash: str) -> dict:
        return {
            "username": username,
            "password_hash": password_hash,
            "totp_secret": None,
            "totp_pending": None,
            "totp_last_counter": None,
            "totp_recovery": None,
            "failure_count": 0,
            "lockout_until": 0.0,
            "created_at": time.time(),
        }

    # ── Account listing / existence ───────────────────────────────────────────

    def has_any_user(self) -> bool:
        with self._lock:
            return bool(self._load_users())

    def list_usernames(self) -> list[str]:
        """Display-form usernames (not the lowercase lookup keys), for the CLI reset tool."""
        with self._lock:
            return [u["username"] for u in self._load_users().values()]

    def get_username_display(self, key_or_username: str) -> Optional[str]:
        with self._lock:
            rec = self._load_users().get(self._key(key_or_username))
            return rec["username"] if rec else None

    # ── Account creation ───────────────────────────────────────────────────────

    def create_user(self, username: str, password: str) -> None:
        """
        Create a new examiner account. Raises ValueError (username/password rules) or
        UsernameTakenError. Callers decide whether this requires an existing session first
        (the API layer only allows it unauthenticated for the very first account).
        """
        username = validate_username(username)
        validate_password_strength(password)
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            if key in users:
                raise UsernameTakenError("That username is already taken.")
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            users[key] = self._new_user_record(username, hashed.decode("utf-8"))
            self._save_users(users)

    def create_first_user_if_none_exist(self, username: str, password: str) -> bool:
        """
        Atomically create the very first account only if none exists yet.

        Guards against a first-run TOCTOU race: two concurrent first-run setup requests both
        reading has_any_user() == False before either writes. The check and the write happen
        under the same lock here, so only the first caller ever succeeds.

        Returns True if this call created the account, False if at least one account already
        existed (no changes made) — the caller should then reject with "use signup while logged
        in, or log in".
        """
        username = validate_username(username)
        validate_password_strength(password)
        with self._lock:
            users = self._load_users()
            if users:
                return False
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            users[self._key(username)] = self._new_user_record(username, hashed.decode("utf-8"))
            self._save_users(users)
            return True

    def set_user_password(self, username: str, new_password: str) -> bool:
        """
        Overwrite an existing user's password directly, with no old-password check — this is
        the primitive the forgotten-password CLI tool uses (tools/reset_user_password.py); it is
        never exposed over the API. Returns False if the username does not exist.
        """
        validate_password_strength(new_password)
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            if key not in users:
                return False
            hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
            users[key]["password_hash"] = hashed.decode("utf-8")
            users[key]["failure_count"] = 0
            users[key]["lockout_until"] = 0.0
            self._save_users(users)
            return True

    def disable_totp_for(self, username: str) -> bool:
        """Used by the CLI reset tool when an examiner has lost both their password and their
        authenticator device. Returns False if the username does not exist."""
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            if key not in users:
                return False
            for field in ("totp_secret", "totp_pending", "totp_last_counter", "totp_recovery"):
                users[key][field] = None
            self._save_users(users)
            return True

    # ── Password verification ─────────────────────────────────────────────────

    def verify_credentials(self, username: str, password: str) -> bool:
        """Constant-time-enough bcrypt comparison. Returns False for an unknown username too,
        without distinguishing why (never reveals whether an account exists)."""
        with self._lock:
            rec = self._load_users().get(self._key(username))
        if not rec:
            # Still run a bcrypt comparison against a dummy hash so a nonexistent username does
            # not respond measurably faster than a wrong password for a real one.
            bcrypt.checkpw(password.encode("utf-8"), bcrypt.hashpw(b"decoy", bcrypt.gensalt()))
            return False
        return bcrypt.checkpw(password.encode("utf-8"), rec["password_hash"].encode("utf-8"))

    # ── Two-factor (TOTP), per user ────────────────────────────────────────────

    def totp_enabled(self, username: str) -> bool:
        with self._lock:
            rec = self._load_users().get(self._key(username))
            return bool(rec and rec.get("totp_secret"))

    def begin_totp_enrollment(self, username: str) -> str:
        """Create a pending secret for this user. It only becomes active after confirm_totp()
        sees a valid code."""
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            rec = users.get(key)
            if not rec:
                raise ValueError("Unknown user.")
            if rec.get("totp_secret"):
                raise ValueError("Two-factor authentication is already enabled.")
            secret = totp.generate_secret()
            rec["totp_pending"] = encrypt_text(secret)
            self._save_users(users)
            return secret

    def confirm_totp(self, username: str, code: str) -> Optional[list[str]]:
        """Activate two-factor for this user. Returns the one-time recovery codes (shown once),
        or None if the code was wrong."""
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            rec = users.get(key)
            pending = rec.get("totp_pending") if rec else None
            if not pending:
                return None
            secret = decrypt_text(pending)
            ok, counter = totp.verify(secret, code)
            if not ok:
                return None
            rec["totp_secret"] = encrypt_text(secret)
            rec["totp_last_counter"] = counter
            rec["totp_pending"] = None
            codes = self._new_recovery_codes_for(rec)
            self._save_users(users)
            return codes

    # ── Recovery codes (lost-authenticator fallback — NOT a forgotten-password fallback) ──────

    def _new_recovery_codes_for(self, rec: dict) -> list[str]:
        """Caller holds self._lock and passes the user's own record (mutated in place). Only
        salted hashes are stored (encrypted); the plain codes are returned to show once."""
        codes = ["".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) + "-" +
                 "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) for _ in range(RECOVERY_CODE_COUNT)]
        entries = []
        for c in codes:
            salt = secrets.token_hex(8)
            entries.append({"s": salt, "h": hashlib.sha256((salt + _norm_recovery(c)).encode()).hexdigest()})
        rec["totp_recovery"] = encrypt_text(json.dumps(entries))
        return codes

    def regenerate_recovery_codes(self, username: str) -> list[str]:
        with self._lock:
            users = self._load_users()
            rec = users.get(self._key(username))
            if not rec or not rec.get("totp_secret"):
                raise ValueError("Two-factor authentication is not enabled.")
            codes = self._new_recovery_codes_for(rec)
            self._save_users(users)
            return codes

    def recovery_codes_remaining(self, username: str) -> int:
        with self._lock:
            rec = self._load_users().get(self._key(username))
        stored = rec.get("totp_recovery") if rec else None
        return len(json.loads(decrypt_text(stored))) if stored else 0

    def verify_recovery_code(self, username: str, code: str) -> bool:
        """One-time use: a matching code is removed."""
        with self._lock:
            users = self._load_users()
            rec = users.get(self._key(username))
            stored = rec.get("totp_recovery") if rec else None
            if not stored:
                return False
            entries = json.loads(decrypt_text(stored))
            norm = _norm_recovery(code)
            for e in entries:
                if hmac.compare_digest(e["h"], hashlib.sha256((e["s"] + norm).encode()).hexdigest()):
                    entries.remove(e)
                    rec["totp_recovery"] = encrypt_text(json.dumps(entries))
                    self._save_users(users)
                    return True
            return False

    def verify_second_factor(self, username: str, code: str) -> bool:
        """A 6-digit authenticator code, or (when it does not look like one) a one-time recovery code."""
        c = (code or "").strip()
        if re.fullmatch(r"\d{3}\s?\d{3}", c):
            return self.verify_totp(username, c)
        return self.verify_recovery_code(username, c)

    def verify_totp(self, username: str, code: str) -> bool:
        """Verify a login code; a code (counter) can be used only once."""
        with self._lock:
            users = self._load_users()
            rec = users.get(self._key(username))
            if not rec:
                return False
            stored = rec.get("totp_secret")
            if not stored:
                return True                       # not enabled: nothing to check
            last = rec.get("totp_last_counter")
            last = int(last) if last is not None else -1
            ok, counter = totp.verify(decrypt_text(stored), code, last)
            if ok:
                rec["totp_last_counter"] = counter
                self._save_users(users)
            return ok

    def disable_totp(self, username: str) -> None:
        with self._lock:
            users = self._load_users()
            rec = users.get(self._key(username))
            if not rec:
                return
            for field in ("totp_secret", "totp_pending", "totp_last_counter", "totp_recovery"):
                rec[field] = None
            self._save_users(users)

    # ── Lockout management, per user ──────────────────────────────────────────

    def is_locked_out(self, username: str) -> tuple[bool, int]:
        """Return (locked_out: bool, seconds_remaining: int). Unknown usernames are never
        reported as locked (verify_credentials already fails them without revealing why). An
        unreadable stored value fails CLOSED — treated as if the limit had just been reached —
        rather than silently letting the account back in."""
        with self._lock:
            rec = self._load_users().get(self._key(username))
            if not rec:
                return False, 0
            try:
                lockout_until = float(rec.get("lockout_until") or 0.0)
            except (TypeError, ValueError):
                return True, self.LOCKOUT_SECONDS
            if time.time() < lockout_until:
                return True, int(lockout_until - time.time())
            return False, 0

    def record_failure(self, username: str) -> tuple[int, bool]:
        """
        Record one failed login attempt for this username. Returns (failure_count, just_locked_out).
        If the username does not exist, still returns a plausible-looking count so the response
        shape (and timing) does not reveal that the account is unknown.
        """
        with self._lock:
            users = self._load_users()
            key = self._key(username)
            rec = users.get(key)
            if not rec:
                return 1, False
            try:
                rec["failure_count"] = int(rec.get("failure_count") or 0) + 1
            except (TypeError, ValueError):
                rec["failure_count"] = self.MAX_FAILURES     # unreadable counter: fail closed
            just_locked = False
            try:
                lockout_until = float(rec.get("lockout_until") or 0.0)
            except (TypeError, ValueError):
                lockout_until = 0.0
            if rec["failure_count"] >= self.MAX_FAILURES and lockout_until <= time.time():
                rec["lockout_until"] = time.time() + self.LOCKOUT_SECONDS
                just_locked = True
            self._save_users(users)
            return rec["failure_count"], just_locked

    def record_success(self, username: str) -> None:
        """Reset the failure counter for this username on successful login."""
        with self._lock:
            users = self._load_users()
            rec = users.get(self._key(username))
            if not rec:
                return
            rec["failure_count"] = 0
            rec["lockout_until"] = 0.0
            self._save_users(users)

    # ── Session management ─────────────────────────────────────────────────────

    def create_session(self, username: str) -> str:
        """Generate a cryptographically random session token bound to this username, store it
        with the current timestamp, and return the token string."""
        token = secrets.token_urlsafe(32)
        display_name = self.get_username_display(username) or username
        with self._lock:
            now = time.time()
            self._sessions[token] = {"username": display_name, "last_activity": now, "created": now}
        return token

    def validate_session(self, token: Optional[str]) -> bool:
        """
        Check whether token corresponds to a live, non-expired session.

        This performs the ACTIVE enforcement of session timeout:
          elapsed = now - last_activity
          if elapsed > SESSION_TIMEOUT_MINUTES * 60 -> delete session, return False

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
                del self._sessions[token]
                return False
            if now - session.get("created", now) > _max_session_hours() * 3600:
                del self._sessions[token]
                return False
            return True

    def session_username(self, token: Optional[str]) -> Optional[str]:
        """The username a valid session belongs to, or None. Does not itself check expiry —
        call validate_session() first (the auth middleware already does, on every request)."""
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            return session["username"] if session else None

    def touch_session(self, token: str) -> None:
        """Update last_activity timestamp on every valid request to keep the session alive
        while the examiner is actively using the tool."""
        with self._lock:
            if token in self._sessions:
                self._sessions[token]["last_activity"] = time.time()

    def invalidate_session(self, token: Optional[str]) -> None:
        """Delete a session (logout)."""
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def invalidate_other_sessions_for_user(self, username: str, keep_token: Optional[str]) -> int:
        """
        End every OTHER session belonging to the SAME username (after that user changes a
        security setting, e.g. enabling/disabling 2FA) — never touches another examiner's
        sessions. Returns how many ended.
        """
        key = self._key(username)
        with self._lock:
            drop = [t for t, s in self._sessions.items()
                    if t != keep_token and self._key(s["username"]) == key]
            for t in drop:
                del self._sessions[t]
            return len(drop)

    def session_count(self) -> int:
        """Return the number of active sessions across all examiners (diagnostics only)."""
        with self._lock:
            return len(self._sessions)
