"""Encryption at rest, two-factor login, signed reports, upload cap."""

import json
import sqlite3
from pathlib import Path

import pytest

from backend import report_signing, secure_store, totp


# ── secure_store ─────────────────────────────────────────────────────────────

def test_encrypt_roundtrip_and_prefix():
    token = secure_store.encrypt_text("[0.1, 0.2, 0.3]")
    assert token.startswith("enc1:") and "0.1" not in token
    assert secure_store.decrypt_text(token) == "[0.1, 0.2, 0.3]"
    assert secure_store.encrypt_text("x") != secure_store.encrypt_text("x")           # random IV each time


def test_legacy_plaintext_still_readable():
    assert secure_store.decrypt_text("[1, 2]") == "[1, 2]"


def test_tampered_or_wrong_key_ciphertext_is_rejected(monkeypatch):
    token = secure_store.encrypt_text("secret")
    mid = len(token) // 2                                                            # inside the ciphertext, never in padding bits
    flipped = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1:]
    with pytest.raises(ValueError):
        secure_store.decrypt_text(flipped)
    monkeypatch.setenv("SIH_DATA_KEY", "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=")
    with pytest.raises(ValueError):
        secure_store.decrypt_text(token)


def test_face_embeddings_are_encrypted_in_the_database():
    from backend.database import Database
    from backend.face_search import FaceEmbeddingRecord

    db = Database()                                      # uses the isolated FORENSIC_CASE_DIR of the test session
    seg_id = "seg-enc-1"
    rec = FaceEmbeddingRecord(frame_offset_seconds=1.0, bbox=[1, 2, 3, 4], embedding=[0.25, -0.5, 0.75])
    db.save_face_embeddings(seg_id, [rec])
    con = sqlite3.connect(db._path)
    raw = con.execute("SELECT embedding_json FROM face_embeddings WHERE segment_id=?", (seg_id,)).fetchone()[0]
    con.close()
    assert raw.startswith("enc1:") and "0.25" not in raw                             # ciphertext at rest
    back = db.list_face_embeddings_for_segments([seg_id])[0]
    assert back["embedding"] == [0.25, -0.5, 0.75]                                  # transparent to callers


# ── TOTP ─────────────────────────────────────────────────────────────────────

_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"      # ASCII "12345678901234567890"


@pytest.mark.parametrize("t,expected8", [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                                         (1234567890, "89005924"), (2000000000, "69279037")])
def test_totp_matches_rfc6238_vectors(t, expected8):
    # RFC 6238 Appendix B lists 8-digit codes; the 6-digit code is the same number modulo 10^6.
    assert totp.code_at(_RFC_SECRET, t // 30) == expected8[-6:]


def test_totp_window_replay_and_format():
    now = 1_700_000_000.0
    c = totp.counter_now(now)
    code = totp.code_at(_RFC_SECRET, c)
    assert totp.verify(_RFC_SECRET, code, now=now) == (True, c)
    assert totp.verify(_RFC_SECRET, totp.code_at(_RFC_SECRET, c - 1), now=now)[0] is True       # clock skew tolerated
    assert totp.verify(_RFC_SECRET, totp.code_at(_RFC_SECRET, c - 3), now=now)[0] is False      # too old
    assert totp.verify(_RFC_SECRET, code, last_used_counter=c, now=now)[0] is False            # replay refused
    for bad in ("", "12345", "1234567", "abcdef", None):
        assert totp.verify(_RFC_SECRET, bad, now=now)[0] is False
    assert totp.otpauth_uri(_RFC_SECRET).startswith("otpauth://totp/")


def _enable_totp(client):
    r = client.post("/api/auth/totp/enroll")
    assert r.status_code == 200
    secret = r.json()["secret"]
    assert client.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 400   # wrong code does not enable
    assert client.get("/api/auth/totp").json()["enabled"] is False
    ok = client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, totp.counter_now())})
    assert ok.status_code == 200
    return secret


def test_two_factor_login_flow(auth_client, monkeypatch):
    secret = _enable_totp(auth_client)
    assert auth_client.get("/api/auth/totp").json()["enabled"] is True
    assert auth_client.post("/api/auth/totp/enroll").status_code == 409                      # already enabled

    auth_client.post("/api/auth/logout")
    st = auth_client.get("/api/auth/status").json()
    assert st["totp_enabled"] is True

    from backend.tests.conftest import _AUTH_TEST_PASSWORD as pw

    base = totp.counter_now()
    monkeypatch.setattr(totp, "counter_now", lambda now=None: base + 5)                       # a later 30 s step for login
    good = totp.code_at(secret, base + 5)

    no_code = auth_client.post("/api/auth/login", json={"password": pw})
    bad_code = auth_client.post("/api/auth/login", json={"password": pw, "totp_code": "000000"})
    bad_pw = auth_client.post("/api/auth/login", json={"password": "wrong-password-xx", "totp_code": good})
    assert no_code.status_code == bad_code.status_code == bad_pw.status_code == 401
    assert no_code.json()["detail"] == bad_code.json()["detail"] == bad_pw.json()["detail"]   # reveals nothing about which

    ok = auth_client.post("/api/auth/login", json={"password": pw, "totp_code": good})
    assert ok.status_code == 200 and auth_client.get("/api/cases").status_code == 200

    auth_client.post("/api/auth/logout")
    replay = auth_client.post("/api/auth/login", json={"password": pw, "totp_code": good})
    assert replay.status_code == 401                                                          # same code cannot be reused


def test_disable_requires_password_and_code(auth_client, monkeypatch):
    secret = _enable_totp(auth_client)
    from backend.tests.conftest import _AUTH_TEST_PASSWORD as pw
    base = totp.counter_now()
    monkeypatch.setattr(totp, "counter_now", lambda now=None: base + 4)
    assert auth_client.post("/api/auth/totp/disable", json={"password": pw, "code": "000000"}).status_code == 401
    assert auth_client.post("/api/auth/totp/disable", json={"password": "nope-nope-nope", "code": totp.code_at(secret, base + 4)}).status_code == 401
    assert auth_client.post("/api/auth/totp/disable", json={"password": pw, "code": totp.code_at(secret, base + 4)}).status_code == 200
    assert auth_client.get("/api/auth/totp").json()["enabled"] is False


def test_totp_secret_is_encrypted_in_the_database(auth_client):
    import backend.main as m
    secret = _enable_totp(auth_client)
    stored = m.db.get_auth_value("totp_secret")
    assert stored.startswith("enc1:") and secret not in stored


# ── Signed reports ───────────────────────────────────────────────────────────

def _fake_pdf(tmp_path, body=b"%PDF-1.4 report body"):
    p = tmp_path / "report_20260101_000000.pdf"
    p.write_bytes(body)
    return p


def test_sign_and_verify_roundtrip(tmp_path):
    pdf = _fake_pdf(tmp_path)
    rec = report_signing.sign_report(pdf, "case-1")
    assert rec["algorithm"] == "Ed25519" and len(rec["signature"]) == 128
    assert report_signing.verify_report(pdf)[0] == "valid"
    assert report_signing.verify_report(pdf, expected_public_key=rec["public_key"])[0] == "valid"


def test_modified_pdf_and_forged_signature_are_detected(tmp_path):
    pdf = _fake_pdf(tmp_path)
    report_signing.sign_report(pdf, "case-1")
    pdf.write_bytes(pdf.read_bytes() + b" edited")
    assert report_signing.verify_report(pdf)[0] == "modified"

    pdf2 = _fake_pdf(tmp_path / "..", b"%PDF other")
    pdf2 = pdf2.rename(tmp_path / "report_2.pdf")
    rec = report_signing.sign_report(pdf2, "case-1")
    sp = report_signing.sig_path(pdf2)
    forged = dict(rec); forged["case_id"] = "case-2"                                 # claim it belongs to another case
    sp.write_text(json.dumps(forged))
    assert report_signing.verify_report(pdf2)[0] == "invalid"
    sp.write_text("garbage")
    assert report_signing.verify_report(pdf2)[0] == "invalid"
    sp.unlink()
    assert report_signing.verify_report(pdf2)[0] == "unsigned"


def test_signature_from_a_different_key_fails_pinning(tmp_path, monkeypatch):
    pdf = _fake_pdf(tmp_path)
    pinned = report_signing.public_key_hex()
    monkeypatch.setenv("SIH_REPORT_SIGNING_KEY", "11" * 32)                          # attacker signs with their own key
    report_signing.sign_report(pdf, "case-1")
    assert report_signing.verify_report(pdf)[0] == "valid"                            # self-consistent...
    assert report_signing.verify_report(pdf, expected_public_key=pinned)[0] == "invalid"   # ...but not the pinned key


def test_api_report_is_signed_logged_and_verifiable(auth_client, tmp_path):
    r = auth_client.post("/api/cases", json={"case_number": "SIGN-1", "examiner": "Test Inspector"})
    cid = r.json()["case_id"]
    img = tmp_path / "e.dd"; img.write_bytes(b"\x00" * 4096)
    auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(img)})
    rep = auth_client.get(f"/api/cases/{cid}/report")
    assert rep.status_code == 200
    name = [a for a in auth_client.get(f"/api/cases/{cid}/audit").json()["entries"] if a["action"] == "report_generated"][-1]["details"]
    fname = Path(name.split(" sha256=")[0]).name
    v = auth_client.get(f"/api/cases/{cid}/report/verify", params={"name": fname}).json()
    assert v["signature"] == "valid" and v["recorded_in_audit_log"] is True

    import backend.database as dbmod
    pdf = dbmod.get_case_report_dir(cid) / fname
    pdf.write_bytes(pdf.read_bytes() + b"tamper")
    v2 = auth_client.get(f"/api/cases/{cid}/report/verify", params={"name": fname}).json()
    assert v2["signature"] == "modified" and v2["recorded_in_audit_log"] is False

    assert auth_client.get(f"/api/cases/{cid}/report/verify", params={"name": "../../etc/passwd"}).status_code == 400
    key = auth_client.get("/api/report-signing-key").json()
    assert key["algorithm"] == "Ed25519" and len(key["public_key"]) == 64 and len(key["key_id"]) == 16


# ── Upload cap ───────────────────────────────────────────────────────────────

def test_upload_over_limit_is_rejected_and_removed(auth_client, monkeypatch):
    monkeypatch.setenv("SIH_MAX_UPLOAD_GB", "0.001")                                  # ~1 MiB
    r = auth_client.post("/api/cases", json={"case_number": "UPL-1", "examiner": "Test Inspector"})
    cid = r.json()["case_id"]
    big = auth_client.post(f"/api/cases/{cid}/evidence/upload", files={"file": ("big.dd", b"\x01" * (3 * 1024 * 1024))})
    assert big.status_code == 413 and "SIH_MAX_UPLOAD_GB" in big.json()["detail"]
    import backend.database as dbmod
    ev_dir = dbmod.get_case_evidence_dir(cid)
    assert not any(ev_dir.glob("big*")) if ev_dir.exists() else True
    small = auth_client.post(f"/api/cases/{cid}/evidence/upload", files={"file": ("ok.dd", b"\x01" * 4096)})
    assert small.status_code == 200
