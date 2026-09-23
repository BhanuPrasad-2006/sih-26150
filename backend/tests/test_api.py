"""
test_api.py — Integration tests for FastAPI endpoints.

All tests use the `auth_client` fixture from conftest.py, which provides a
TestClient backed by a fresh in-memory Database in a temporary directory,
pre-authenticated so the auth middleware does not block requests.
No test can write to C:/sih_cases or ~/sih_cases.
"""

import time

import pytest


# ── Regression: open a case that has no evidence ─────────────────────────────

def test_open_case_no_evidence(auth_client):
    """
    Exact reproduction of the reported bug:
      1. Create a case.
      2. Immediately GET /api/cases/{id} (no evidence loaded, no scan run).
      3. The response must be HTTP 200 with evidence=[], segments=[], log_events=[], audit=[]
      4. The frontend guard `(caseObj.evidence ?? []).length` must evaluate to 0.

    Before the fix this returned a bare Case object with no 'evidence' key,
    causing `caseObj.evidence.length` → TypeError in the browser.
    """
    # Step 1 — create case
    create_res = auth_client.post("/api/cases", json={
        "case_number": "REGRESSION-NO-EVIDENCE",
        "examiner": "Test Inspector",
        "notes": "Regression test — no evidence loaded"
    })
    assert create_res.status_code == 200, create_res.text
    case_id = create_res.json()["case_id"]

    # Step 2 — immediately open the case (no evidence, no scan)
    get_res = auth_client.get(f"/api/cases/{case_id}")
    assert get_res.status_code == 200, get_res.text

    data = get_res.json()

    # Step 3 — all child arrays must be present and empty
    assert "evidence" in data,    "'evidence' key missing from GET /api/cases/{id} response"
    assert "segments" in data,    "'segments' key missing from GET /api/cases/{id} response"
    assert "log_events" in data,  "'log_events' key missing from GET /api/cases/{id} response"
    assert "audit" in data,       "'audit' key missing from GET /api/cases/{id} response"

    assert data["evidence"]   == [], f"expected evidence=[], got {data['evidence']}"
    assert data["segments"]   == [], f"expected segments=[], got {data['segments']}"
    assert data["log_events"] == [], f"expected log_events=[], got {data['log_events']}"

    # Step 4 — simulate what the frontend does: (caseObj.evidence ?? []).length
    evidence = data["evidence"] or []   # Python equivalent of ?? []
    assert len(evidence) == 0


# ── Duplicate case number → HTTP 409 ─────────────────────────────────────────

def test_duplicate_case_number_returns_409(auth_client):
    """
    Creating two cases with the same case_number must return HTTP 409 with a
    clear error message identifying the duplicate.
    """
    payload = {
        "case_number": "DUPE-2026-001",
        "examiner": "Test Inspector",
        "notes": ""
    }
    first = auth_client.post("/api/cases", json=payload)
    assert first.status_code == 200, first.text

    second = auth_client.post("/api/cases", json=payload)
    assert second.status_code == 409, f"Expected 409, got {second.status_code}: {second.text}"

    detail = second.json().get("detail", "")
    assert "DUPE-2026-001" in detail, (
        f"Error message should name the duplicate case number; got: {detail!r}"
    )
    assert "already exists" in detail.lower(), (
        f"Error message should say 'already exists'; got: {detail!r}"
    )


# ── Full lifecycle test ───────────────────────────────────────────────────────

def test_case_lifecycle(auth_client, dahua_img_path):
    """
    Full happy-path: create case → GET case (with empty arrays) → add evidence
    → start scan → check segments → check audit.
    """
    # 1. Create Case
    create_res = auth_client.post("/api/cases", json={
        "case_number": "LIFECYCLE-2026-001",
        "examiner": "Inspector Test",
        "notes": "Unit test case"
    })
    assert create_res.status_code == 200, create_res.text
    case_data = create_res.json()
    case_id = case_data["case_id"]

    # 2. GET case — verify child arrays are present and empty
    get_res = auth_client.get(f"/api/cases/{case_id}")
    assert get_res.status_code == 200, get_res.text
    case_detail = get_res.json()
    assert case_detail["evidence"] == []
    assert case_detail["segments"] == []

    # 3. List Cases
    list_res = auth_client.get("/api/cases")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 4. Add Evidence
    ev_res = auth_client.post(f"/api/cases/{case_id}/evidence", json={
        "path": dahua_img_path
    })
    assert ev_res.status_code == 200, ev_res.text
    ev_data = ev_res.json()
    assert "evidence_id" in ev_data

    # 5. Trigger Scan
    scan_res = auth_client.post(f"/api/cases/{case_id}/scan")
    assert scan_res.status_code == 200
    assert scan_res.json()["status"] == "started"

    # 6. Check Segments endpoint
    seg_res = auth_client.get(f"/api/cases/{case_id}/segments")
    assert seg_res.status_code == 200

    # 7. Check Audit Log
    audit_res = auth_client.get(f"/api/cases/{case_id}/audit")
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert audit_data["chain_intact"] is True

    # 8. GET case after evidence added — evidence array must now be non-empty
    get_res2 = auth_client.get(f"/api/cases/{case_id}")
    assert get_res2.status_code == 200
    case_detail2 = get_res2.json()
    assert len(case_detail2["evidence"]) == 1, (
        f"Expected 1 evidence item, got {len(case_detail2['evidence'])}"
    )

    # 9. scan_status must reflect real progress, not always show "PENDING"
    # (a real bug: the field didn't exist on the backend at all, so the
    # frontend's `ev.scan_status || 'PENDING'` fallback always won).
    for _ in range(50):
        case_detail2 = auth_client.get(f"/api/cases/{case_id}").json()
        if case_detail2["evidence"][0]["scan_status"] == "COMPLETED":
            break
        time.sleep(0.1)
    assert case_detail2["evidence"][0]["scan_status"] == "COMPLETED", (
        f"Expected scan_status COMPLETED once segments exist, "
        f"got {case_detail2['evidence'][0]['scan_status']!r}"
    )


def test_hikvision_real_video_through_api(auth_client, temp_dir):
    """
    The exact flow the UI drives, for a Hikvision-style image holding a REAL
    ffmpeg-encoded H.264 stream: add evidence -> scan -> list segments -> export
    -> verify. Previously the Hikvision carver produced one useless single-NAL
    "segment" per start code and nothing was exportable.
    """
    import os
    import subprocess

    from backend.exporter import ffmpeg_available, ffprobe_available
    from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET

    if not (ffmpeg_available() and ffprobe_available()):
        pytest.skip("ffmpeg/ffprobe not on PATH")

    h264_path = os.path.join(temp_dir, "clip.h264")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
         "-f", "h264", h264_path],
        check=True,
    )
    stream = open(h264_path, "rb").read()

    img = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    img += HIKV_MASTER_SECTOR_MAGIC + b"\x00" * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    img += b"\xCC" * 4096 + stream + b"\xCC" * 4096
    disk_path = os.path.join(temp_dir, "hik_real.dd")
    with open(disk_path, "wb") as f:
        f.write(img)

    case_id = auth_client.post("/api/cases", json={
        "case_number": "HIK-REAL-VIDEO-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    assert auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": disk_path}).status_code == 200
    assert auth_client.post(f"/api/cases/{case_id}/scan").json()["status"] == "started"

    segments = []
    for _ in range(100):
        segments = auth_client.get(f"/api/cases/{case_id}/segments").json()
        if segments:
            break
        time.sleep(0.1)
    assert len(segments) == 1, f"expected one recovered stream, got {len(segments)}"
    seg = segments[0]
    assert seg["status"] == "UNCERTAIN"
    assert seg["frame_count"] == 10

    exp = auth_client.post(f"/api/cases/{case_id}/export/{seg['segment_id']}")
    assert exp.status_code == 200, exp.text
    body = exp.json()
    assert "error" not in body["detail"], body["detail"]
    assert body["detail"]["ffprobe_valid"] is True
    assert body["segment"]["status"] == "PARTIAL"


def test_upload_evidence_endpoint(auth_client, temp_dir):
    """
    Test POST /api/cases/{case_id}/evidence/upload saves the uploaded file
    and returns a valid Evidence object.
    """
    import os
    case_res = auth_client.post("/api/cases", json={
        "case_number": "UPLOAD-TEST-001", "examiner": "Examiner Bhanu", "notes": ""
    })
    assert case_res.status_code == 200
    case_id = case_res.json()["case_id"]

    dummy_content = b"DUMMY_RAW_EVIDENCE_BYTES_12345"
    files = {"file": ("test_sample.raw", dummy_content, "application/octet-stream")}
    data = {"device_utc_offset_minutes": "330"}

    up_res = auth_client.post(f"/api/cases/{case_id}/evidence/upload", files=files, data=data)
    assert up_res.status_code == 200, up_res.text
    ev_data = up_res.json()

    assert "evidence_id" in ev_data
    assert ev_data["case_id"] == case_id
    assert ev_data["device_utc_offset_minutes"] == 330
    assert os.path.exists(ev_data["path"])
    with open(ev_data["path"], "rb") as f:
        assert f.read() == dummy_content

    # Confirm case evidence list now includes the uploaded evidence
    case_detail = auth_client.get(f"/api/cases/{case_id}").json()
    assert len(case_detail["evidence"]) == 1
    assert case_detail["evidence"][0]["evidence_id"] == ev_data["evidence_id"]


# ── Verify integrity survives a server restart, and detects tampering ────────

def _wait_for_segments(client, case_id, timeout_s=10.0):
    end = time.time() + timeout_s
    while time.time() < end:
        segs = client.get(f"/api/cases/{case_id}/segments").json()
        if segs:
            return segs
        time.sleep(0.1)
    return []


def _wait_scan_finished(client, case_id, timeout_s=10.0):
    end = time.time() + timeout_s
    while time.time() < end:
        ev = client.get(f"/api/cases/{case_id}").json()["evidence"][0]
        if ev.get("sha256_after"):
            return ev
        time.sleep(0.1)
    return client.get(f"/api/cases/{case_id}").json()["evidence"][0]


def test_verify_works_without_in_memory_image_and_detects_tampering(auth_client, dahua_img_path):
    import backend.main as main_mod

    case_id = auth_client.post("/api/cases", json={
        "case_number": "VERIFY-RESTART-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": dahua_img_path})
    auth_client.post(f"/api/cases/{case_id}/scan")
    _wait_scan_finished(auth_client, case_id)

    # Simulate a server restart: the in-memory image handles are gone.
    main_mod._open_images.clear()
    ok = auth_client.get(f"/api/cases/{case_id}/verify")
    assert ok.status_code == 200, ok.text
    assert ok.json()["unchanged"] is True

    # Tamper with the evidence file: verify must now report a change.
    with open(dahua_img_path, "r+b") as f:
        f.seek(4)
        f.write(b"\xFF\xFE")
    bad = auth_client.get(f"/api/cases/{case_id}/verify")
    assert bad.status_code == 200, bad.text
    assert bad.json()["unchanged"] is False


def test_verify_before_any_evidence_is_a_clean_400(auth_client):
    case_id = auth_client.post("/api/cases", json={
        "case_number": "VERIFY-NOEV-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    res = auth_client.get(f"/api/cases/{case_id}/verify")
    assert res.status_code == 400


# ── Generic fallback for unidentified recorders ──────────────────────────────

def _make_real_h264(temp_dir):
    import os
    import subprocess

    from backend.exporter import ffmpeg_available, ffprobe_available

    if not (ffmpeg_available() and ffprobe_available()):
        pytest.skip("ffmpeg/ffprobe not on PATH")
    p = os.path.join(temp_dir, "gen.h264")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", p],
        check=True,
    )
    return open(p, "rb").read()


def test_unidentified_recorder_uses_generic_stream_carving(auth_client, temp_dir):
    import os

    stream = _make_real_h264(temp_dir)
    disk_path = os.path.join(temp_dir, "unknown_recorder.dd")
    with open(disk_path, "wb") as f:
        f.write(b"\xCC" * 8192 + stream + b"\xCC" * 8192)   # no brand marker anywhere

    case_id = auth_client.post("/api/cases", json={
        "case_number": "GENERIC-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": disk_path})
    auth_client.post(f"/api/cases/{case_id}/scan")

    segments = _wait_for_segments(auth_client, case_id)
    assert len(segments) == 1
    ev = auth_client.get(f"/api/cases/{case_id}").json()["evidence"][0]
    assert "generic stream carving" in ev["brand"].lower()

    exp = auth_client.post(f"/api/cases/{case_id}/export/{segments[0]['segment_id']}")
    assert exp.status_code == 200, exp.text
    assert exp.json()["detail"]["ffprobe_valid"] is True
    assert exp.json()["segment"]["status"] == "PARTIAL"


def test_unidentified_recorder_without_video_recovers_nothing(auth_client, temp_dir):
    import os

    disk_path = os.path.join(temp_dir, "noise.dd")
    with open(disk_path, "wb") as f:
        f.write(os.urandom(256 * 1024))
    case_id = auth_client.post("/api/cases", json={
        "case_number": "GENERIC-NONE-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": disk_path})
    auth_client.post(f"/api/cases/{case_id}/scan")
    time.sleep(1.5)
    assert auth_client.get(f"/api/cases/{case_id}/segments").json() == []


# ── Evidence upload ──────────────────────────────────────────────────────────

def test_upload_evidence_stores_file_and_sanitises_name(auth_client):
    case_id = auth_client.post("/api/cases", json={
        "case_number": "UPLOAD-001", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    payload = b"\xCC" * 4096
    res = auth_client.post(
        f"/api/cases/{case_id}/evidence/upload",
        files={"file": ("..\\..\\evil name?.dd", payload, "application/octet-stream")},
        data={"device_utc_offset_minutes": "330"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    import os
    stored = body["path"]
    assert os.path.isfile(stored)
    assert open(stored, "rb").read() == payload
    name = os.path.basename(stored)
    assert "?" not in name and "/" not in name and "\\" not in name   # odd characters neutralised
    assert os.path.dirname(os.path.abspath(stored)).endswith(os.path.join(case_id, "evidence"))  # no traversal out of the case dir
    assert body["device_utc_offset_minutes"] == 330


def test_upload_evidence_rejects_bad_offset_and_unknown_case(auth_client):
    case_id = auth_client.post("/api/cases", json={
        "case_number": "UPLOAD-002", "examiner": "Inspector Test", "notes": "",
    }).json()["case_id"]
    bad = auth_client.post(f"/api/cases/{case_id}/evidence/upload",
                           files={"file": ("a.dd", b"x", "application/octet-stream")},
                           data={"device_utc_offset_minutes": "9999"})
    assert bad.status_code == 400
    missing = auth_client.post("/api/cases/does-not-exist/evidence/upload",
                               files={"file": ("a.dd", b"x", "application/octet-stream")})
    assert missing.status_code == 404
