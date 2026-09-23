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
