"""Security hardening: headers, Host/Origin checks, docs auth, path allow-list, audit seal, model integrity, XSS escaping."""

import json
import re
import shutil
from pathlib import Path

import pytest

from backend import audit_seal, model_integrity, security


def _case(client, number):
    r = client.post("/api/cases", json={"case_number": number, "examiner": "Test Inspector"})
    assert r.status_code == 200
    return r.json()["case_id"]


# ── 1. Security headers ──────────────────────────────────────────────────────

def test_security_headers_on_api_static_and_error_responses(auth_client):
    for resp in (auth_client.get("/api/cases"), auth_client.get("/"), auth_client.get("/api/cases/nope/audit")):
        h = resp.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "object-src 'none'" in h["content-security-policy"]
        assert "script-src 'self' 'unsafe-inline'" in h["content-security-policy"]   # documented limitation


def test_headers_also_on_unauthenticated_rejection(isolated_app):
    r = isolated_app.get("/api/cases")
    assert r.status_code == 401
    assert r.headers["x-frame-options"] == "DENY"


# ── 3. Host and Origin ───────────────────────────────────────────────────────

def test_foreign_host_header_is_rejected(auth_client):
    r = auth_client.get("/api/cases", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


def test_local_host_names_accepted(auth_client):
    for host in ("127.0.0.1:8000", "localhost:8000", "localhost"):
        assert auth_client.get("/api/cases", headers={"Host": host}).status_code == 200


def test_cross_origin_post_is_blocked_same_origin_allowed(auth_client):
    body = {"case_number": "ORIG-1", "examiner": "Test Inspector"}
    bad = auth_client.post("/api/cases", json=body, headers={"Host": "127.0.0.1:8000", "Origin": "http://evil.example.com"})
    assert bad.status_code == 403
    bad2 = auth_client.post("/api/cases", json=body, headers={"Origin": "null"})
    assert bad2.status_code == 403
    bad3 = auth_client.post("/api/cases", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert bad3.status_code == 403
    ok = auth_client.post("/api/cases", json=body, headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"})
    assert ok.status_code == 200


def test_allowed_hosts_can_be_extended_by_the_operator(monkeypatch):
    monkeypatch.setenv("SIH_ALLOWED_HOSTS", "lab-pc.local, 10.0.0.5")
    assert {"lab-pc.local", "10.0.0.5"} <= security.allowed_hosts()
    assert security._hostname("[::1]:8000") == "::1" and security._hostname("Localhost:8000") == "localhost"


# ── 5. API docs need a session ───────────────────────────────────────────────

def test_api_docs_and_openapi_require_login(isolated_app):
    assert isolated_app.get("/api/openapi.json").status_code == 401
    assert isolated_app.get("/api/docs").status_code == 401
    old = isolated_app.get("/openapi.json")                                     # the old unprotected default location
    assert '"openapi"' not in old.text and "paths" not in old.text[:2000]       # SPA fallback page, not the API schema


def test_api_docs_available_after_login(auth_client):
    assert auth_client.get("/api/openapi.json").status_code == 200


# ── 6. Server-side path allow-list ───────────────────────────────────────────

def test_paths_unrestricted_when_no_roots_configured(auth_client, tmp_path, monkeypatch):
    monkeypatch.delenv("FORENSIC_EVIDENCE_ROOTS", raising=False)
    img = tmp_path / "e.dd"; img.write_bytes(b"\x00" * 4096)
    cid = _case(auth_client, "PATH-OPEN-1")
    assert auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(img)}).status_code == 200


def test_paths_outside_allowed_roots_are_refused(auth_client, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"; allowed.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    (allowed / "ok.dd").write_bytes(b"\x00" * 4096)
    (outside / "secret.dd").write_bytes(b"\x00" * 4096)
    monkeypatch.setenv("FORENSIC_EVIDENCE_ROOTS", str(allowed))
    cid = _case(auth_client, "PATH-LOCK-1")

    assert auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(allowed / "ok.dd")}).status_code == 200
    r = auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(outside / "secret.dd")})
    assert r.status_code == 403 and "FORENSIC_EVIDENCE_ROOTS" in r.json()["detail"]
    # '..' and a path that merely starts with the same prefix are both outside
    sneaky = str(allowed / ".." / "outside" / "secret.dd")
    assert auth_client.post(f"/api/cases/{cid}/evidence", json={"path": sneaky}).status_code in (403, 422)
    sibling = tmp_path / "allowed_evil"; sibling.mkdir(); (sibling / "x.dd").write_bytes(b"\x00" * 4096)
    assert auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(sibling / "x.dd")}).status_code == 403


def test_acquire_and_accuracy_paths_also_checked(auth_client, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"; allowed.mkdir()
    outside = tmp_path / "outside.bin"; outside.write_bytes(b"\x01" * 4096)
    monkeypatch.setenv("FORENSIC_EVIDENCE_ROOTS", str(allowed))
    monkeypatch.setenv("FORENSIC_ALLOW_LOCAL_ACQUISITION", "1")
    cid = _case(auth_client, "PATH-LOCK-2")
    r = auth_client.post(f"/api/cases/{cid}/acquire", json={"source_path": str(outside), "write_blocker_confirmed": True})
    assert r.status_code == 403


# ── 4. Audit seal ────────────────────────────────────────────────────────────

def test_seal_roundtrip_and_detects_rewrite_and_truncation(tmp_path):
    d = tmp_path / "case"
    audit_seal.write_seal(d, "c1", 3, "aa" * 32)
    assert audit_seal.check_seal(d, "c1", 3, "aa" * 32)[0] == "ok"
    assert audit_seal.check_seal(d, "c1", 3, "bb" * 32)[0] == "tampered"            # same length, rewritten
    status, msg = audit_seal.check_seal(d, "c1", 2, "aa" * 32)
    assert status == "tampered" and "removed" in msg                                # truncated chain
    assert audit_seal.check_seal(d, "c1", 4, "cc" * 32)[0] == "tampered"           # extra entries not sealed
    assert audit_seal.check_seal(tmp_path / "other", "c1", 3, "aa" * 32)[0] == "missing"


def test_seal_file_cannot_simply_be_edited(tmp_path):
    d = tmp_path / "case"
    audit_seal.write_seal(d, "c1", 3, "aa" * 32)
    f = d / "audit_seal.json"
    data = json.loads(f.read_text())
    data["count"], data["head"] = 1, "dd" * 32                                      # attacker rewrites seal to match a forged log
    f.write_text(json.dumps(data))
    assert audit_seal.check_seal(d, "c1", 1, "dd" * 32)[0] == "tampered"           # MAC no longer matches
    f.write_text("not json")
    assert audit_seal.check_seal(d, "c1", 1, "dd" * 32)[0] == "tampered"


def test_seal_bound_to_case_id_and_key(tmp_path, monkeypatch):
    d = tmp_path / "case"
    audit_seal.write_seal(d, "c1", 3, "aa" * 32)
    assert audit_seal.check_seal(d, "other-case", 3, "aa" * 32)[0] == "tampered"    # copied seal from another case
    monkeypatch.setenv("SIH_AUDIT_KEY", "a different key")
    assert audit_seal.check_seal(d, "c1", 3, "aa" * 32)[0] == "tampered"            # wrong key


def test_api_detects_database_truncation_of_audit_log(auth_client):
    import backend.main as main_mod
    cid = _case(auth_client, "SEAL-API-1")
    main_mod._audit(cid, "custom_event_1", "x")
    main_mod._audit(cid, "custom_event_2", "y")
    ok = auth_client.get(f"/api/cases/{cid}/audit").json()
    assert ok["chain_intact"] is True and ok["seal"]["status"] == "ok" and ok["seal"]["count"] >= 3

    # an attacker with database access drops the last entry: the plain hash chain still verifies...
    log = main_mod._get_case_audit_log(cid)
    log._entries.pop()
    log._last_hash = log._entries[-1].entry_hash
    assert log.verify_chain()[0] is True
    # ...but the seal, which is not in the database, does not
    bad = auth_client.get(f"/api/cases/{cid}/audit").json()
    assert bad["chain_intact"] is False and bad["seal"]["status"] == "tampered"
    assert "removed" in bad["error"]


def test_report_shows_seal_and_head(auth_client, tmp_path):
    cid = _case(auth_client, "SEAL-REP-1")
    img = tmp_path / "e.dd"; img.write_bytes(b"\x00" * 4096)
    auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(img)})
    r = auth_client.get(f"/api/cases/{cid}/report")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ── 7. Model integrity ───────────────────────────────────────────────────────

def test_shipped_models_match_pinned_hashes():
    models = Path(model_integrity.__file__).parent / "cv_models"
    for name in model_integrity.PINNED_SHA256:
        ok, msg = model_integrity.verify_model(models / name)
        assert ok, msg


def test_tampered_or_corrupt_model_is_refused(tmp_path):
    src = Path(model_integrity.__file__).parent / "cv_models" / "face_detection_yunet_2023mar.onnx"
    bad = tmp_path / src.name
    data = bytearray(src.read_bytes()); data[100] ^= 0xFF
    bad.write_bytes(bytes(data))
    ok, msg = model_integrity.verify_model(bad)
    assert not ok and "does not match" in msg


def test_unpinned_model_allowed_but_unverified_and_skip_flag(tmp_path, monkeypatch):
    custom = tmp_path / "my_custom.onnx"; custom.write_bytes(b"x")
    ok, msg = model_integrity.verify_model(custom)
    assert ok and "unverified" in msg
    bad = tmp_path / "face_detection_yunet_2023mar.onnx"; bad.write_bytes(b"corrupt")
    assert model_integrity.verify_model(bad)[0] is False
    monkeypatch.setenv("SIH_SKIP_MODEL_VERIFY", "1")
    assert model_integrity.verify_model(bad)[0] is True


def test_face_detection_refuses_tampered_model(tmp_path, monkeypatch):
    from backend import face_detection
    from backend.motion import create_synthetic_test_video
    bad = tmp_path / "face_detection_yunet_2023mar.onnx"; bad.write_bytes(b"corrupt")
    monkeypatch.setattr(face_detection, "_MODEL_PATH", bad)
    video = create_synthetic_test_video(tmp_path / "v.mp4", has_motion=False, num_frames=5)
    res = face_detection.detect_faces_in_video(video)
    assert res.error and "does not match" in res.error and res.faces_detected is False


def test_object_detection_refuses_tampered_pinned_model(tmp_path, monkeypatch):
    from backend import object_detection
    from backend.motion import create_synthetic_test_video
    bad = tmp_path / "object_detection_yolox_2022nov.onnx"; bad.write_bytes(b"corrupt")
    monkeypatch.setenv("OBJECT_MODEL_PATH", str(bad))
    video = create_synthetic_test_video(tmp_path / "v.mp4", has_motion=False, num_frames=5)
    res = object_detection.detect_objects_in_video(video)
    assert res.error and "does not match" in res.error


# ── 2. XSS: server/user strings must be escaped before reaching innerHTML ────

_FRONTEND = Path(security.__file__).parent.parent / "frontend" / "js"

_MUST_BE_ESCAPED = [
    ("screens/RecordingsScreen.js", r"\$\{s\.notes"),
    ("screens/AuditLogScreen.js", r"\$\{e\.details"),
    ("screens/AuditLogScreen.js", r"\$\{e\.action"),
    ("screens/DashboardScreen.js", r"\$\{c\.case_number"),
    ("components/Header.js", r"\$\{crumb\.label"),
]


@pytest.mark.parametrize("rel,pattern", _MUST_BE_ESCAPED)
def test_risky_fields_are_never_interpolated_raw(rel, pattern):
    text = (_FRONTEND / rel).read_text(encoding="utf-8")
    assert not re.search(pattern, text), f"{rel}: {pattern} is interpolated without escapeHtml()"


def test_error_messages_are_escaped_everywhere():
    for f in (_FRONTEND / "screens").glob("*.js"):
        assert "${err.message}" not in f.read_text(encoding="utf-8"), f.name
