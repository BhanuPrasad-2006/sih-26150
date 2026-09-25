"""
case_package.py — Passphrase-encrypted, tamper-evident case package (.sihpkg).

For handing a case over or archiving it: everything except the (huge, already hashed) evidence images is zipped
with a manifest of SHA-256 hashes, then encrypted with AES-256-GCM under a key derived from the passphrase with
scrypt. Each 1 MiB chunk is authenticated, and the chunk index and a final-chunk flag are part of the
authenticated data, so reordering, truncating or editing any part is detected on decryption.

Format:  b"SIHPKG1\\n" | salt(16) | scrypt n,r,p (u32 x3) | chunk*   with chunk = len(u32) | nonce(12) | ciphertext+tag
CLI:     python -m backend.case_package decrypt case.sihpkg out.zip
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"SIHPKG1\n"
CHUNK = 1024 * 1024
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSPHRASE = 12


class PackageError(Exception):
    pass


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _nonce(index: int) -> bytes:
    return b"\x00\x00\x00\x00" + struct.pack(">Q", index)


def _aad(index: int, final: bool) -> bytes:
    return struct.pack(">QB", index, 1 if final else 0)


def build_zip(case_dir: Path, exclude_dirs: tuple[str, ...] = ("evidence", "packages")) -> bytes:
    """Zip a case folder (minus evidence images) with a manifest.json of SHA-256 hashes."""
    buf = io.BytesIO()
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "case_dir": case_dir.name,
                "excluded": list(exclude_dirs), "files": {}}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(case_dir.rglob("*")):
            rel = f.relative_to(case_dir)
            if not f.is_file() or rel.parts[0] in exclude_dirs:
                continue
            data = f.read_bytes()
            manifest["files"][rel.as_posix()] = hashlib.sha256(data).hexdigest()
            z.writestr(rel.as_posix(), data)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def encrypt_bytes(plain: bytes, passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise PackageError(f"The passphrase must be at least {MIN_PASSPHRASE} characters.")
    salt = os.urandom(16)
    key = AESGCM(_derive(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P))
    out = bytearray(MAGIC + salt + struct.pack(">III", SCRYPT_N, SCRYPT_R, SCRYPT_P))
    n_chunks = max(1, -(-len(plain) // CHUNK))
    for i in range(n_chunks):
        final = i == n_chunks - 1
        ct = key.encrypt(_nonce(i), plain[i * CHUNK:(i + 1) * CHUNK], _aad(i, final))
        out += struct.pack(">I", len(ct)) + _nonce(i)[4:] + ct
    return bytes(out)


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28:
        raise PackageError("Not a case package.")
    pos = len(MAGIC)
    salt = blob[pos:pos + 16]; pos += 16
    n, r, p = struct.unpack(">III", blob[pos:pos + 12]); pos += 12
    if not (2 ** 12 <= n <= 2 ** 20 and 1 <= r <= 16 and 1 <= p <= 4):
        raise PackageError("Unreasonable key-derivation parameters (file corrupted or hostile).")
    key = AESGCM(_derive(passphrase, salt, n, r, p))
    chunks = []
    while pos < len(blob):
        if pos + 4 + 8 > len(blob):
            raise PackageError("Truncated package.")
        (clen,) = struct.unpack(">I", blob[pos:pos + 4]); pos += 4
        nonce_tail = blob[pos:pos + 8]; pos += 8
        ct = blob[pos:pos + clen]; pos += clen
        if len(ct) != clen:
            raise PackageError("Truncated package.")
        chunks.append((nonce_tail, ct))
    if not chunks:
        raise PackageError("Empty package.")
    plain = bytearray()
    for i, (nonce_tail, ct) in enumerate(chunks):
        try:
            plain += key.decrypt(b"\x00\x00\x00\x00" + nonce_tail, ct, _aad(i, i == len(chunks) - 1))
        except InvalidTag:
            raise PackageError("Wrong passphrase, or the package was modified, reordered or truncated.")
    return bytes(plain)


def create_package(case_dir: Path, dest: Path, passphrase: str) -> dict:
    blob = encrypt_bytes(build_zip(case_dir), passphrase)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return {"file": dest.name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "decrypt":
        import getpass
        Path(sys.argv[3]).write_bytes(decrypt_bytes(Path(sys.argv[2]).read_bytes(), getpass.getpass("Passphrase: ")))
        print("decrypted ->", sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)
