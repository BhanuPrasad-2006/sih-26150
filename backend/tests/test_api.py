"""
test_api.py — Integration tests for FastAPI endpoints.

All tests use the `auth_client` fixture from conftest.py, which provides a
TestClient backed by a fresh in-memory Database in a temporary directory,
pre-authenticated so the auth middleware does not block requests.
No test can write to C:/sih_cases or ~/sih_cases.
"""

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
