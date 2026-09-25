"""
pdf_signing.py — Embedded (PAdES-style) digital signature inside the report PDF, in addition to the detached
Ed25519 signature in report_signing.py.

A signature embedded in the PDF is what PDF viewers (Adobe Acrobat, Foxit, Okular, pyHanko) recognise and show
as "Signed": any change to the file afterwards turns the signature invalid there too, without needing our tool.

Key material: an ECDSA P-256 key and a self-signed certificate ("SIH DVR/NVR Forensic Tool - report signer")
created on first use in SIH_KEY_DIR (report_signer_key.pem, report_signer_cert.pem; the key file is mode 600).
Because the certificate is self-signed, a viewer shows the signature as *intact* but the signer as *unknown* until
the certificate is trusted; verify against the published certificate instead (GET /api/report-signing-cert).

What this proves: the PDF is byte-for-byte what the tool produced (integrity) and was produced by the holder of the
key (origin). It does not prove the identity of a person.
"""

from __future__ import annotations

import datetime as dt
import io
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from backend.secure_store import key_dir

FIELD_NAME = "SIHForensicSignature"


def _paths() -> tuple[Path, Path]:
    d = key_dir()
    return d / "report_signer_key.pem", d / "report_signer_cert.pem"


def ensure_signer_material() -> tuple[Path, Path]:
    key_path, cert_path = _paths()
    if key_path.is_file() and cert_path.is_file():
        return key_path, cert_path
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "SIH DVR/NVR Forensic Tool - report signer"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SIH26150"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key_path, cert_path


def certificate_pem() -> str:
    return ensure_signer_material()[1].read_text()


def embed_signature(pdf: Path, reason: str = "Report issued by the SIH DVR/NVR Forensic Tool",
                    location: str = "") -> None:
    """Sign `pdf` in place with an incremental-update signature."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers

    key_path, cert_path = ensure_signer_material()
    signer = signers.SimpleSigner.load(str(key_path), str(cert_path))
    meta = signers.PdfSignatureMetadata(field_name=FIELD_NAME, reason=reason, location=location or None,
                                        md_algorithm="sha256")
    with open(pdf, "rb") as inf:
        writer = IncrementalPdfFileWriter(inf)
        out = signers.sign_pdf(writer, meta, signer=signer)
        data = out.getvalue() if isinstance(out, io.BytesIO) else out.read()
    tmp = pdf.with_suffix(".signing.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, pdf)


def verify_embedded(pdf: Path) -> tuple[str, str]:
    """
    Returns (status, message): 'valid' (intact, signed by this tool's certificate), 'modified' (content changed
    after signing), 'untrusted' (intact but signed by a different certificate), 'unsigned', or 'invalid'.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    from pyhanko.keys import load_cert_from_pemder

    try:
        with open(pdf, "rb") as f:
            reader = PdfFileReader(f)
            sigs = reader.embedded_signatures
            if not sigs:
                return "unsigned", "The PDF contains no embedded signature."
            _, cert_path = _paths()
            trust = [load_cert_from_pemder(str(cert_path))] if cert_path.is_file() else []
            vc = ValidationContext(trust_roots=trust, allow_fetching=False)
            status = validate_pdf_signature(sigs[-1], vc)
            if not status.intact or not status.valid:
                return "modified", "The PDF was changed after it was signed (or the signature is corrupt)."
            if not status.trusted:
                return "untrusted", "Signature is intact but not from this tool's certificate."
            return "valid", "Embedded signature is valid and from this tool's certificate; the PDF is unchanged."
    except Exception as exc:
        return "invalid", f"The embedded signature could not be validated: {exc}"
