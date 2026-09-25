"""
security_status.py — A live self-check of this installation's security posture, shown in the UI.

Each check returns {id, title, status, detail} with status one of:
  ok    the control is in place
  warn  a control is available but not enabled / cannot be confirmed - act on it
  info  informational
The check never changes anything and never reveals key material.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from pathlib import Path

from backend.secure_store import key_dir


def _check(cid: str, title: str, status: str, detail: str) -> dict:
    return {"id": cid, "title": title, "status": status, "detail": detail}


def disk_encryption_status(path: Path) -> tuple[str, str]:
    """('on'|'off'|'unknown', detail) for the volume that holds `path`. Best effort, no administrator rights."""
    try:
        if platform.system() == "Windows":
            drive = (path.resolve().drive or "C:").rstrip("\\") + "\\"
            ps = ("(New-Object -ComObject Shell.Application).NameSpace('%s').Self."
                  "ExtendedProperty('System.Volume.BitLockerProtection')" % drive)
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,  # nosec B603 B607
                                 timeout=15).stdout.strip()
            if out == "1":
                return "on", f"BitLocker protection is ON for {drive}"
            if out in ("0", "3"):
                return "off", f"BitLocker protection is OFF for {drive}"
            return "unknown", f"BitLocker state of {drive} could not be read (value: {out or 'none'})"
        if platform.system() == "Linux":
            src = subprocess.run(["findmnt", "-no", "SOURCE", "--target", str(path)], capture_output=True,  # nosec B603 B607
                                 text=True, timeout=10).stdout.strip()
            if src:
                types = subprocess.run(["lsblk", "-s", "-no", "TYPE", src], capture_output=True, text=True,  # nosec B603 B607
                                       timeout=10).stdout.split()
                return ("on", "The volume sits on a dm-crypt/LUKS device") if "crypt" in types else \
                       ("off", "No encryption layer found under the volume")
    except Exception:
        pass
    return "unknown", "Disk encryption could not be determined on this system"


def run_checks(*, totp_enabled: bool, recovery_remaining: int, https: bool, case_dir: Path,
               evidence_roots: list, seal_states: dict[str, str], model_ok: bool, acquisition_enabled: bool) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check("2fa", "Two-factor login",
                         "ok" if totp_enabled else "warn",
                         (f"On; {recovery_remaining} recovery codes left" if totp_enabled
                          else "Off. Turn it on from the dashboard (Two-factor).")))
    if totp_enabled and recovery_remaining <= 2:
        checks.append(_check("recovery", "Recovery codes", "warn",
                             f"Only {recovery_remaining} left; generate new ones."))
    checks.append(_check("tls", "HTTPS", "ok" if https else "warn",
                         "This session uses HTTPS." if https else
                         "This session is plain HTTP on localhost. Start with SIH_TLS=1 for HTTPS (Secure cookie, HSTS)."))
    host = os.environ.get("SIH_HOST", "127.0.0.1")
    local = host in ("127.0.0.1", "localhost", "::1")
    checks.append(_check("bind", "Network exposure", "ok" if local else "warn",
                         "Listening on localhost only." if local else f"Bound to {host}: reachable from the network."))

    kd = key_dir()
    key_files = [kd / n for n in ("audit.key", "data.key", "report_signing.key", "report_signer_key.pem")]
    present = [k for k in key_files if k.is_file()]
    loose = []
    if os.name != "nt":
        loose = [k.name for k in present if stat.S_IMODE(k.stat().st_mode) & 0o077]
    env_keys = any(os.environ.get(v) for v in ("SIH_AUDIT_KEY", "SIH_DATA_KEY", "SIH_REPORT_SIGNING_KEY"))
    if loose:
        checks.append(_check("keys", "Key files", "warn", f"Readable by other users: {', '.join(loose)}"))
    else:
        checks.append(_check("keys", "Key files", "ok",
                             f"{len(present)} key file(s) in {kd}" + ("; some keys come from the environment" if env_keys else "")
                             + ". Back them up away from the database."))

    state, detail = disk_encryption_status(case_dir)
    checks.append(_check("disk", "Disk encryption of the case drive",
                         {"on": "ok", "off": "warn", "unknown": "warn"}[state], detail
                         + ("" if state == "on" else ". Evidence, exports and PDFs are not encrypted by the application."))
                  )
    checks.append(_check("roots", "Server-side path allow-list", "ok" if evidence_roots else "info",
                         "FORENSIC_EVIDENCE_ROOTS is set." if evidence_roots else
                         "Not set: any local path can be loaded (fine on a personal workstation, set it on a shared machine)."))
    bad = {k: v for k, v in seal_states.items() if v == "tampered"}
    checks.append(_check("seal", "Audit log seals", "warn" if bad else "ok",
                         ("Seal mismatch: " + ", ".join(bad)) if bad else "Audit logs match their seals."))
    checks.append(_check("models", "Analytics model files", "ok" if model_ok else "warn",
                         "All pinned models match their SHA-256." if model_ok else "A model file failed its integrity check."))
    checks.append(_check("imaging", "Drive imaging", "info",
                         "Enabled (FORENSIC_ALLOW_LOCAL_ACQUISITION=1): use a write blocker." if acquisition_enabled else "Disabled (default)."))
    return checks
