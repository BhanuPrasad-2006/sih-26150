"""Examiner-entered Section 63(4) certificate details: cleaning, storage per case, API, and what the PDF prints."""

import base64
import re
import zlib
from pathlib import Path

import pytest

from backend import certificate_meta as cm
from backend.models import Case, Evidence
from backend.reporting import generate_report


def _pdf_text(path: Path) -> str:
    """All text drawn in an (unsigned) ReportLab PDF: decode each ASCII85+Flate content stream."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", path.read_bytes(), re.S):
        data = m.group(1).strip()
        try:
            out.append(zlib.decompress(base64.a85decode(data[:-2] if data.endswith(b"~>") else data)).decode("latin-1"))
        except Exception:
            continue
    strings = re.findall(r"\((.*?)(?<!\\)\) Tj", "\n".join(out))      # every text string, in drawing order
    return re.sub(r"\s+", " ", " ".join(strings))


def _report(tmp_path, details):
    case = Case(case_number="C-1", examiner="Examiner")
    ev = Evidence(case_id=case.case_id, path="x.dd")
    pdf = tmp_path / "r.pdf"
    generate_report(pdf, case, ev, [], [], [], True, None, None, None, None, details)
    return _pdf_text(pdf)


# ── cleaning ──────────────────────────────────────────────────────────────────

def test_clean_keeps_only_known_fields_as_trimmed_single_lines():
    out = cm.clean({"police_station": "  Cyber   PS \n Hyderabad ", "fir_number": None, "evil": "x", "device_serial": "SN\x00\x1f1"})
    assert set(out) == set(cm.FIELD_KEYS)
    assert out["police_station"] == "Cyber PS Hyderabad"
    assert out["fir_number"] == "" and out["seizure_officer"] == ""
    assert out["device_serial"] == "SN 1"


def test_clean_caps_length():
    assert len(cm.clean({"police_station": "x" * 5000})["police_station"]) == cm.MAX_FIELD_LENGTH


def test_missing_labels_lists_the_blank_fields():
    assert cm.missing_labels(None) == [label for _, label in cm.FIELDS]
    full = {k: "v" for k in cm.FIELD_KEYS}
    assert cm.missing_labels(full) == []
    assert cm.missing_labels({**full, "device_serial": ""}) == [cm.LABELS["device_serial"]]


# ── API ───────────────────────────────────────────────────────────────────────

def _case(auth_client, number):
    return auth_client.post("/api/cases", json={"case_number": number, "examiner": "Tester", "notes": ""}).json()["case_id"]


def test_details_start_empty_then_save_and_reload(auth_client):
    cid = _case(auth_client, "CERT-1")
    first = auth_client.get(f"/api/cases/{cid}/certificate").json()
    assert [f["key"] for f in first["fields"]] == cm.FIELD_KEYS
    assert all(v == "" for v in first["values"].values())

    body = {"police_station": "Cyber PS", "fir_number": "FIR 12/2026", "seizure_officer": "A. Sharma",
            "seizure_officer_rank": "Inspector", "device_make_model": "Dahua XVR5108", "device_serial": "SN-0042"}
    saved = auth_client.put(f"/api/cases/{cid}/certificate", json=body)
    assert saved.status_code == 200 and saved.json()["missing"] == []
    assert auth_client.get(f"/api/cases/{cid}/certificate").json()["values"] == body


def test_details_are_kept_per_case(auth_client):
    a, b = _case(auth_client, "CERT-A"), _case(auth_client, "CERT-B")
    auth_client.put(f"/api/cases/{a}/certificate", json={"fir_number": "ONLY-A"})
    assert auth_client.get(f"/api/cases/{b}/certificate").json()["values"]["fir_number"] == ""


def test_partial_save_reports_what_is_missing(auth_client):
    cid = _case(auth_client, "CERT-2")
    r = auth_client.put(f"/api/cases/{cid}/certificate", json={"fir_number": "F-1"}).json()
    assert cm.LABELS["fir_number"] not in r["missing"] and cm.LABELS["device_serial"] in r["missing"]


def test_unknown_case_is_404_and_unknown_fields_are_ignored(auth_client):
    assert auth_client.get("/api/cases/nope/certificate").status_code == 404
    assert auth_client.put("/api/cases/nope/certificate", json={}).status_code == 404
    cid = _case(auth_client, "CERT-3")
    r = auth_client.put(f"/api/cases/{cid}/certificate", json={"fir_number": "F", "admin": "yes"})
    assert r.status_code == 200 and "admin" not in r.json()["values"]


def test_saving_is_written_to_the_audit_log_without_the_values(auth_client):
    cid = _case(auth_client, "CERT-4")
    auth_client.put(f"/api/cases/{cid}/certificate", json={"fir_number": "SECRET-FIR-77"})
    audit = auth_client.get(f"/api/cases/{cid}/audit").json()
    entries = [e for e in audit["entries"] if e["action"] == "certificate_details_saved"]
    assert entries and "fir_number" in entries[-1]["details"]
    assert "SECRET-FIR-77" not in entries[-1]["details"]


def test_details_need_a_session():
    from fastapi.testclient import TestClient
    import backend.main as m
    with TestClient(m.app) as anonymous:
        assert anonymous.get("/api/cases/x/certificate").status_code == 401
        assert anonymous.put("/api/cases/x/certificate", json={}).status_code == 401


# ── the PDF ───────────────────────────────────────────────────────────────────

def test_report_prints_the_entered_details_and_says_they_are_unverified(tmp_path):
    text = _report(tmp_path, {"police_station": "Cyber PS Hyderabad", "fir_number": "FIR 12/2026",
                              "seizure_officer": "A. Sharma", "seizure_officer_rank": "Inspector",
                              "device_make_model": "Dahua XVR5108", "device_serial": "SN-0042"})
    for expected in ("Cyber PS Hyderabad", "FIR 12/2026", "A. Sharma, Inspector",
                     "Dahua XVR5108", "SN-0042", "as entered by the examiner", "has not verified them"):
        assert expected in text, expected
    assert "Not provided:" not in text


def test_report_lists_blank_fields_instead_of_hiding_them(tmp_path):
    text = _report(tmp_path, {"fir_number": "FIR 1/2026"})
    assert "FIR 1/2026" in text
    assert "not provided" in text
    assert "Not provided:" in text and "Recorder serial number" in text and "Police station / agency" in text


def test_report_without_any_details_still_builds_and_says_none_were_provided(tmp_path):
    text = _report(tmp_path, None)
    assert "not provided" in text and "Not provided: Police station / agency" in text
