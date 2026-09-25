"""
totp.py — RFC 6238 time-based one-time passwords (HMAC-SHA1, 6 digits, 30 s), standard library only.
Compatible with Google Authenticator, Microsoft Authenticator, Authy, 1Password, etc.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1          # accept the previous / current / next 30 s step (clock skew)


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret_b32: str, counter: int) -> str:
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    num = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(num).zfill(DIGITS)


def counter_now(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def verify(secret_b32: str, code: str, last_used_counter: int = -1, now: Optional[float] = None) -> tuple[bool, int]:
    """
    Check `code` against the current window. A counter at or below `last_used_counter` is refused, so a code
    cannot be replayed (for example by someone who watched it being typed). Returns (ok, counter_matched).
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return False, last_used_counter
    c0 = counter_now(now)
    for c in range(c0 - WINDOW, c0 + WINDOW + 1):
        if c > last_used_counter and hmac.compare_digest(code_at(secret_b32, c), code):
            return True, c
    return False, last_used_counter


def otpauth_uri(secret_b32: str, account: str = "examiner", issuer: str = "SIH DVR-NVR Forensic Tool") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")
