"""
audit_seal.py — A keyed seal over the audit chain head, stored outside the database.

The audit log is a plain SHA-256 chain: editing one entry breaks the chain, but someone with database access
can rewrite every entry and recompute the hashes, or simply delete the last entries (a truncated chain is still
a valid chain). The seal closes both holes for anyone who does NOT also hold the key and the case folder:

    seal = HMAC-SHA256(key, case_id | entry_count | head_hash)

written to <case folder>/audit_seal.json after every audit entry. The key comes from SIH_AUDIT_KEY, or from a
file created on first use in SIH_KEY_DIR (default ~/.sih_forensic/audit.key), never from the database.

Limits (stated in the report): an attacker with the key AND the case folder can forge a seal. The head hash and
count are also printed in the PDF report, so a printed copy detects even that.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger(__name__)


def _key_file() -> Path:
    base = os.environ.get("SIH_KEY_DIR", "").strip()
    return (Path(base) if base else Path.home() / ".sih_forensic") / "audit.key"


def _key() -> bytes:
    env = os.environ.get("SIH_AUDIT_KEY", "")
    if env:
        return env.encode("utf-8")
    kf = _key_file()
    if kf.is_file():
        return bytes.fromhex(kf.read_text().strip())
    kf.parent.mkdir(parents=True, exist_ok=True)
    k = secrets.token_bytes(32)
    kf.write_text(k.hex())
    try:
        os.chmod(kf, 0o600)
    except OSError:
        pass
    return k


def _mac(case_id: str, count: int, head: str) -> str:
    return hmac.new(_key(), f"{case_id}|{count}|{head}".encode("utf-8"), hashlib.sha256).hexdigest()


def _seal_path(case_dir: Path) -> Path:
    return case_dir / "audit_seal.json"


def write_seal(case_dir: Path, case_id: str, count: int, head: str) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    data = {"case_id": case_id, "count": count, "head": head, "mac": _mac(case_id, count, head)}
    tmp = _seal_path(case_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, _seal_path(case_dir))


def check_seal(case_dir: Path, case_id: str, count: int, head: str) -> tuple[str, str]:
    """
    Returns (status, message); status is one of
      'ok'       the log matches the seal
      'missing'  no seal exists (case created before sealing); not treated as tampering
      'tampered' the log no longer matches what was sealed, or the seal itself was altered
    """
    sp = _seal_path(case_dir)
    if not sp.is_file():
        return "missing", "No audit seal exists for this case (created before sealing was enabled)."
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        stored_mac, s_count, s_head = data["mac"], int(data["count"]), data["head"]
    except Exception:
        return "tampered", "The audit seal file is unreadable or malformed."
    if not hmac.compare_digest(stored_mac, _mac(case_id, s_count, s_head)):
        return "tampered", "The audit seal's signature is invalid (seal edited, or wrong key)."
    if s_count == count and s_head == head:
        return "ok", f"Audit log matches its seal ({count} entries)."
    if count < s_count:
        return "tampered", f"Audit log has {count} entries but {s_count} were sealed: entries were removed."
    if count > s_count:
        # Entries added after the last seal write (e.g. a crash between append and seal): re-sealing is
        # legitimate only from the tool itself, so report it rather than accept it silently.
        return "tampered", f"Audit log has {count} entries but only {s_count} were sealed."
    return "tampered", "Audit log head does not match the sealed head: entries were rewritten."
