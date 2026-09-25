"""
tls.py — Optional HTTPS for the local server (SIH_TLS=1).

Even on localhost, HTTPS protects the session cookie and evidence data from other software on the machine that can
sniff loopback traffic, and lets the cookie carry the Secure flag and the server send HSTS.

A self-signed certificate for localhost / 127.0.0.1 / ::1 is created on first use in SIH_KEY_DIR/tls/ (key mode 600)
and re-created when it is within 30 days of expiry. Browsers will warn about a self-signed certificate once; import
tls/server.crt into the OS/browser trust store to remove the warning, or supply your own files with
SIH_TLS_CERT / SIH_TLS_KEY.

Start:  SIH_TLS=1  (run.bat / run.sh honour it)   or   python -m backend.serve
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from backend.secure_store import key_dir


def _needs_renewal(cert_path: Path) -> bool:
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        return cert.not_valid_after_utc < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
    except Exception:
        return True


def ensure_cert() -> tuple[Path, Path]:
    """Return (cert_path, key_path), using SIH_TLS_CERT / SIH_TLS_KEY when both are set."""
    env_cert, env_key = os.environ.get("SIH_TLS_CERT", ""), os.environ.get("SIH_TLS_KEY", "")
    if env_cert and env_key:
        return Path(env_cert), Path(env_key)
    d = key_dir() / "tls"
    cert_path, key_path = d / "server.crt", d / "server.key"
    if cert_path.is_file() and key_path.is_file() and not _needs_renewal(cert_path):
        return cert_path, key_path
    d.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SIH DVR/NVR Forensic Tool (local)")])
    now = dt.datetime.now(dt.timezone.utc)
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("::1")),
    ])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365))
            .add_extension(san, critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return cert_path, key_path


if __name__ == "__main__":
    c, k = ensure_cert()
    print(c)
    print(k)
