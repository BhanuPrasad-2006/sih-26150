"""Recovery codes, session lifetime, sealed global log, HTTPS, embedded PDF signatures, encrypted case packages,
security status."""

import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from backend import case_package, pdf_signing, totp, tls
from backend.tests.conftest import _AUTH_TEST_PASSWORD as PW


def _enable_totp_get_codes(client):
    secret = client.post("/api/auth/totp/enroll").json()["secret"]
    r = client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, totp.counter_now())})
    assert r.status_code == 200
    return secret, r.json()["recovery_codes"]


# ── Recovery codes ───────────────────────────────────────────────────────────

def test_enabling_2fa_returns_ten_recovery_codes(auth_client):
    secret, codes = _enable_totp_get_codes(auth_client)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    st = auth_client.get("/api/auth/totp").json()
    assert st["enabled"] is True and st["recovery_codes_remaining"] == 10


def test_recovery_codes_are_not_stored_in_plaintext():
    import backend.main as m
    from backend.auth import AuthManager
    a = AuthManager(m.db)
    if a.totp_enabled():
        a.disable_totp()
    secret = a.begin_totp_enrollment()
    codes = a.confirm_totp(totp.code_at(secret, totp.counter_now()))
    assert codes and len(codes) == 10
    raw = m.db.get_auth_value("totp_recovery")
    assert raw.startswith("enc1:")
    from backend import secure_store
    inner = secure_store.decrypt_text(raw)                                               # even decrypted: hashes only
    assert not any(c.replace("-", "") in inner for c in codes) and "\"h\"" in inner
    a.disable_totp()


def test_login_with_recovery_code_works_once(auth_client):
    secret, codes = _enable_totp_get_codes(auth_client)
    auth_client.post("/api/auth/logout")
    ok = auth_client.post("/api/auth/login", json={"password": PW, "totp_code": codes[0]})
    assert ok.status_code == 200 and auth_client.get("/api/cases").status_code == 200
    assert auth_client.get("/api/auth/totp").json()["recovery_codes_remaining"] == 9
    auth_client.post("/api/auth/logout")
    again = auth_client.post("/api/auth/login", json={"password": PW, "totp_code": codes[0]})
    assert again.status_code == 401                                                    # single use
    lowercase = auth_client.post("/api/auth/login", json={"password": PW, "totp_code": codes[1].lower().replace("-", " ")})
    assert lowercase.status_code == 200                                                # formatting-tolerant
    glog = auth_client.get("/api/auth/global-audit").json()["entries"]
    assert any(e["action"] == "recovery_code_used" for e in glog)


def test_recovery_code_can_disable_2fa_and_regenerate_needs_password(auth_client):
    secret, codes = _enable_totp_get_codes(auth_client)
    assert auth_client.post("/api/auth/totp/recovery-codes", json={"password": "wrong-password-1", "code": codes[0]}).status_code == 401
    fresh = auth_client.post("/api/auth/totp/recovery-codes", json={"password": PW, "code": codes[0]}).json()["recovery_codes"]
    assert len(fresh) == 10 and set(fresh).isdisjoint(codes[1:])                       # old codes are void
    auth_client.post("/api/auth/logout")
    assert auth_client.post("/api/auth/login", json={"password": PW, "totp_code": codes[2]}).status_code == 401
    assert auth_client.post("/api/auth/login", json={"password": PW, "totp_code": fresh[0]}).status_code == 200
    d = auth_client.post("/api/auth/totp/disable", json={"password": PW, "code": fresh[1]})
    assert d.status_code == 200 and auth_client.get("/api/auth/totp").json()["enabled"] is False


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_session_has_an_absolute_lifetime_even_when_active(monkeypatch):
    import backend.auth as auth_mod
    import backend.main as m
    a = auth_mod.AuthManager(m.db)
    monkeypatch.setenv("SESSION_MAX_HOURS", "1")
    t = [1_000_000.0]
    monkeypatch.setattr(auth_mod.time, "time", lambda: t[0])
    token = a.create_session()
    for _ in range(5):                                                                  # active every 20 minutes
        t[0] += 20 * 60
        if t[0] - 1_000_000.0 <= 3600:
            assert a.validate_session(token) is True
            a.touch_session(token)
    t[0] += 20 * 60                                                                     # now > 1 hour since login
    assert a.validate_session(token) is False


def test_enabling_2fa_ends_other_sessions(auth_client):
    import backend.main as m
    other = m.auth.create_session()
    assert m.auth.validate_session(other) is True
    _enable_totp_get_codes(auth_client)
    assert m.auth.validate_session(other) is False
    assert auth_client.get("/api/cases").status_code == 200                             # the current session survives


# ── Sealed global audit log ──────────────────────────────────────────────────

def test_global_audit_truncation_is_detected(auth_client):
    import backend.main as m
    m._global_audit_event("test_event_1", "a")
    m._global_audit_event("test_event_2", "b")
    ok = auth_client.get("/api/auth/global-audit").json()
    assert ok["chain_intact"] is True and ok["seal"]["status"] == "ok"
    m._global_audit._entries.pop()
    m._global_audit._last_hash = m._global_audit._entries[-1].entry_hash
    bad = auth_client.get("/api/auth/global-audit").json()
    assert bad["chain_intact"] is False and bad["seal"]["status"] == "tampered"


# ── HTTPS ────────────────────────────────────────────────────────────────────

def test_self_signed_certificate_is_created_with_local_names_and_key_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("SIH_KEY_DIR", str(tmp_path))
    cert_path, key_path = tls.ensure_cert()
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert {str(i) for i in san.get_values_for_type(x509.IPAddress)} >= {"127.0.0.1", "::1"}
    assert tls.ensure_cert() == (cert_path, key_path)                                    # reused, not regenerated
    if os.name != "nt":
        assert oct(key_path.stat().st_mode & 0o777) == "0o600"


def test_https_gets_secure_cookie_and_hsts_http_does_not(isolated_app):
    from starlette.testclient import TestClient
    import backend.main as m
    https = TestClient(m.app, base_url="https://testserver")
    r = https.post("/api/auth/setup", json={"password": PW})
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower()
    assert r.headers["strict-transport-security"].startswith("max-age=")
    plain = isolated_app.get("/api/auth/status")
    assert "strict-transport-security" not in plain.headers


# ── Embedded PDF signature ───────────────────────────────────────────────────

def _real_report(client, tmp_path, number):
    cid = client.post("/api/cases", json={"case_number": number, "examiner": "Test Inspector"}).json()["case_id"]
    img = tmp_path / "e.dd"; img.write_bytes(b"\x00" * 4096)
    client.post(f"/api/cases/{cid}/evidence", json={"path": str(img)})
    assert client.get(f"/api/cases/{cid}/report").status_code == 200
    import backend.database as dbmod
    pdf = sorted(dbmod.get_case_report_dir(cid).glob("report_*.pdf"))[-1]
    return cid, pdf


def test_report_pdf_carries_a_valid_embedded_signature(auth_client, tmp_path):
    cid, pdf = _real_report(auth_client, tmp_path, "PADES-1")
    assert pdf_signing.verify_embedded(pdf)[0] == "valid"
    v = auth_client.get(f"/api/cases/{cid}/report/verify", params={"name": pdf.name}).json()
    assert v["embedded_signature"] == "valid" and v["signature"] == "valid" and v["recorded_in_audit_log"] is True
    data = bytearray(pdf.read_bytes())
    data[len(data) // 3] ^= 0xFF                                                          # damage the content
    pdf.write_bytes(bytes(data))
    assert pdf_signing.verify_embedded(pdf)[0] in ("modified", "invalid")
    v2 = auth_client.get(f"/api/cases/{cid}/report/verify", params={"name": pdf.name}).json()
    assert v2["signature"] == "modified" and v2["embedded_signature"] in ("modified", "invalid")


def test_signing_certificate_endpoint(auth_client):
    pem = auth_client.get("/api/report-signing-cert").json()["certificate_pem"]
    assert pem.startswith("-----BEGIN CERTIFICATE-----")


# ── Encrypted case package ───────────────────────────────────────────────────

def test_package_roundtrip_and_wrong_passphrase():
    blob = case_package.encrypt_bytes(b"secret case data " * 100, "correct horse battery")
    assert b"secret case data" not in blob
    assert case_package.decrypt_bytes(blob, "correct horse battery") == b"secret case data " * 100
    with pytest.raises(case_package.PackageError):
        case_package.decrypt_bytes(blob, "wrong passphrase here")
    with pytest.raises(case_package.PackageError, match="at least"):
        case_package.encrypt_bytes(b"x", "short")


def test_package_detects_modification_truncation_and_reordering():
    plain = os.urandom(int(2.5 * case_package.CHUNK))                                     # three chunks
    blob = case_package.encrypt_bytes(plain, "a long enough passphrase")
    assert case_package.decrypt_bytes(blob, "a long enough passphrase") == plain

    flipped = bytearray(blob); flipped[len(blob) // 2] ^= 1
    with pytest.raises(case_package.PackageError):
        case_package.decrypt_bytes(bytes(flipped), "a long enough passphrase")
    with pytest.raises(case_package.PackageError):
        case_package.decrypt_bytes(blob[: len(blob) - 50], "a long enough passphrase")     # truncated inside a chunk

    # drop the LAST chunk cleanly: the earlier chunks were authenticated as "not final"
    import struct
    pos = len(case_package.MAGIC) + 16 + 12
    ends = []
    while pos < len(blob):
        (ln,) = struct.unpack(">I", blob[pos:pos + 4]); pos += 4 + 8 + ln; ends.append(pos)
    with pytest.raises(case_package.PackageError):
        case_package.decrypt_bytes(blob[: ends[-2]], "a long enough passphrase")
    # swap two chunks
    starts = [len(case_package.MAGIC) + 28] + ends[:-1]
    c = [blob[s:e] for s, e in zip(starts, ends)]
    swapped = blob[: starts[0]] + c[1] + c[0] + c[2]
    with pytest.raises(case_package.PackageError):
        case_package.decrypt_bytes(swapped, "a long enough passphrase")


def test_package_rejects_hostile_kdf_parameters():
    blob = bytearray(case_package.encrypt_bytes(b"x", "a long enough passphrase"))
    import struct
    struct.pack_into(">III", blob, len(case_package.MAGIC) + 16, 2 ** 30, 8, 1)          # absurd memory cost
    with pytest.raises(case_package.PackageError, match="Unreasonable"):
        case_package.decrypt_bytes(bytes(blob), "a long enough passphrase")


def test_api_package_excludes_evidence_and_is_audited(auth_client, tmp_path):
    cid, pdf = _real_report(auth_client, tmp_path, "PKG-1")
    assert auth_client.post(f"/api/cases/{cid}/package", data={"passphrase": "short"}).status_code == 400
    r = auth_client.post(f"/api/cases/{cid}/package", data={"passphrase": "a long enough passphrase"})
    assert r.status_code == 200 and r.content.startswith(case_package.MAGIC)
    zdata = case_package.decrypt_bytes(r.content, "a long enough passphrase")
    names = zipfile.ZipFile(io.BytesIO(zdata)).namelist()
    assert "manifest.json" in names and "audit_export.json" in names
    assert any(n.startswith("reports/") and n.endswith(".pdf") for n in names)
    assert not any(n.startswith("evidence/") for n in names)
    entries = auth_client.get(f"/api/cases/{cid}/audit").json()["entries"]
    assert any(e["action"] == "case_package_created" for e in entries)


# ── Security status ──────────────────────────────────────────────────────────

def test_security_status_reports_posture_without_leaking_keys(auth_client):
    r = auth_client.get("/api/security/status")
    assert r.status_code == 200
    body = r.json()
    ids = {c["id"]: c for c in body["checks"]}
    assert {"2fa", "tls", "bind", "keys", "disk", "roots", "seal", "models"} <= set(ids)
    assert ids["2fa"]["status"] == "warn" and ids["bind"]["status"] == "ok" and ids["models"]["status"] == "ok"
    from backend.secure_store import key_dir
    for kf in key_dir().glob("*.key"):
        assert kf.read_text().strip() not in r.text
    _enable_totp_get_codes(auth_client)
    assert {c["id"]: c for c in auth_client.get("/api/security/status").json()["checks"]}["2fa"]["status"] == "ok"
