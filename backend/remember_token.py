"""
remember_token.py — Persistent 7-day remembered login management.

Handles issuing, validating, and revoking 7-day persistent login tokens
for local installations. Tokens are encrypted on disk and checked on startup.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Optional

from backend.local_config import CONFIG_DIR
from backend.secure_store import decrypt_text, encrypt_text

log = logging.getLogger("remember_token")

REMEMBER_TOKEN_FILE = CONFIG_DIR / "remember_session.enc"
REMEMBER_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def save_remember_token(username: str, token: str) -> None:
    """Save an encrypted persistent token valid for 7 days."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "username": username,
            "token": token,
            "created_at": time.time(),
            "expires_at": time.time() + REMEMBER_MAX_AGE_SECONDS,
        }
        encrypted = encrypt_text(json.dumps(payload))
        REMEMBER_TOKEN_FILE.write_text(encrypted, encoding="utf-8")
    except Exception as exc:
        log.warning("Could not persist remember token: %s", exc)


def load_remember_token() -> Optional[dict]:
    """
    Load and validate the remember token.
    Returns dict {"username": str, "token": str, "expires_at": float} if valid and not expired,
    or None if missing, corrupt, or expired.
    """
    if not REMEMBER_TOKEN_FILE.is_file():
        return None
    try:
        raw_enc = REMEMBER_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not raw_enc:
            return None
        decrypted = decrypt_text(raw_enc)
        data = json.loads(decrypted)
        now = time.time()
        if data.get("expires_at", 0) <= now:
            clear_remember_token()
            return None
        return data
    except Exception as exc:
        log.warning("Failed to decrypt or parse remember token: %s", exc)
        clear_remember_token()
        return None


def clear_remember_token() -> None:
    """Delete the persisted remember token (called on logout or expiration)."""
    try:
        if REMEMBER_TOKEN_FILE.is_file():
            REMEMBER_TOKEN_FILE.unlink()
    except Exception as exc:
        log.warning("Could not clear remember token file: %s", exc)
