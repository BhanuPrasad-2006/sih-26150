"""
report_signing.py — Detached Ed25519 signatures for generated PDF reports.

Each report gets  <report>.pdf.sig.json  holding the report's SHA-256, an Ed25519 signature over
"SIH-REPORT-V1 | case_id | sha256", the public key and a key id. Anyone with the public key can verify the PDF
has not been changed since this tool produced it; the SHA-256 is also written into the hash-chained audit log.

The private key is created on first use in SIH_KEY_DIR (default ~/.sih_forensic/report_signing.key, mode 600).
Back it up and keep it off the machine that stores the case database. Publish the public key / key id
(GET /api/report-signing-key) so verifiers can pin it.

This is a DETACHED signature, not a signature embedded in the PDF (PAdES). It proves integrity and origin of the
file, not the identity of a person; a person's declaration still goes in the certificate.

CLI:  python -m backend.report_signing verify report.pdf
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from backend.secure_store import key_dir

ALGORITHM = "Ed25519"


def _private_key() -> Ed25519PrivateKey:
    env = os.environ.get("SIH_REPORT_SIGNING_KEY", "").strip()      # hex of the 32-byte seed
    if env:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(env))
    kf = key_dir() / "report_signing.key"
    if kf.is_file():
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(kf.read_text().strip()))
    kf.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    kf.write_text(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption()).hex())
    try:
        os.chmod(kf, 0o600)
    except OSError:
        pass
    return key


def public_key_hex() -> str:
    return _private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def key_id(pub_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _message(case_id: str, sha256: str) -> bytes:
    return f"SIH-REPORT-V1|{case_id}|{sha256}".encode("utf-8")


def sig_path(pdf: Path) -> Path:
    return pdf.with_name(pdf.name + ".sig.json")


def sign_report(pdf: Path, case_id: str) -> dict:
    digest = sha256_file(pdf)
    key = _private_key()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    record = {
        "algorithm": ALGORITHM, "case_id": case_id, "file": pdf.name, "sha256": digest,
        "signature": key.sign(_message(case_id, digest)).hex(), "public_key": pub, "key_id": key_id(pub),
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }
    sig_path(pdf).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def verify_report(pdf: Path, expected_public_key: str | None = None) -> tuple[str, str]:
    """
    Returns (status, message); status is one of
      'valid'    file matches its signature (and the pinned public key, when one is given)
      'modified' the PDF's hash differs from the signed hash
      'invalid'  the signature does not verify, is malformed, or the key differs from the pinned one
      'unsigned' no signature file exists
    """
    sp = sig_path(pdf)
    if not sp.is_file():
        return "unsigned", "No signature file exists for this report."
    try:
        rec = json.loads(sp.read_text(encoding="utf-8"))
        pub_hex, sig_hex, signed_hash, case_id = rec["public_key"], rec["signature"], rec["sha256"], rec["case_id"]
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(sig_hex), _message(case_id, signed_hash))
    except (InvalidSignature, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return "invalid", "The signature file is malformed or its signature does not verify."
    if expected_public_key and expected_public_key.lower() != pub_hex.lower():
        return "invalid", "Signed with a different key than the pinned public key."
    if sha256_file(pdf) != signed_hash:
        return "modified", "The PDF no longer matches the hash that was signed: it was changed after signing."
    return "valid", f"Signature valid (key {key_id(pub_hex)}); the PDF is unchanged since it was signed."


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        status, msg = verify_report(Path(sys.argv[2]))
        print(f"{status.upper()}: {msg}")
        sys.exit(0 if status == "valid" else 1)
    print(__doc__)
    sys.exit(2)
