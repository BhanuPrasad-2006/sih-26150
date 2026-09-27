"""
update_check.py — compares the running version against the VERSION file on GitHub's main branch.

Deliberately simple for a hackathon-stage tool with no formal release process: "the latest
version" is whatever VERSION currently says on `main`, not a signed release artifact. This tells
an examiner a newer version exists; it does not itself vouch for what changed.
"""

from __future__ import annotations

import ssl
import urllib.request
from typing import Optional

_VERSION_URL = "https://raw.githubusercontent.com/BhanuPrasad-2006/sih-26150/main/VERSION"


def _parse(version: str) -> tuple:
    """
    '1.2.10' -> ((1, 2, 10), 1, ''); '1.2.10-dev' -> ((1, 2, 10), 0, 'dev').
    A '-suffix' (pre-release, e.g. "-dev") sorts BEFORE the same plain numeric version — the
    middle element does that ordering; comparing tuples then just works with plain '>'.
    """
    core, sep, suffix = version.strip().partition("-")
    numbers = []
    for p in core.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    return (tuple(numbers), 0 if sep else 1, suffix)


def is_newer(candidate: str, current: str) -> bool:
    try:
        return _parse(candidate) > _parse(current)
    except Exception:
        return False


def fetch_latest_version(timeout: float = 3.0) -> Optional[str]:
    """Returns the VERSION file's contents from GitHub's main branch, or None on any failure
    (offline, GitHub unreachable, rate-limited, ...) — an update check must never break the app."""
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(_VERSION_URL, timeout=timeout, context=ctx) as resp:  # nosec B310: fixed literal HTTPS URL, never built from input
            if resp.status != 200:
                return None
            text = resp.read(256).decode("utf-8", errors="replace").strip()
            return text or None
    except Exception:
        return None


def check_for_update(current_version: str) -> dict:
    latest = fetch_latest_version()
    return {
        "current": current_version,
        "latest": latest,
        "update_available": bool(latest and is_newer(latest, current_version)),
    }
