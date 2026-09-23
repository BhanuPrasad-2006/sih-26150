"""
test_database.py — Tests for database.py segment lifecycle.

Covers a real bug found during manual UI verification: re-running a scan on
the same evidence created a fresh set of segments (new segment_ids every
time) without removing the previous scan's segments, so old and new segments
accumulated side by side with contradictory data instead of the new scan
replacing the old one.
"""

from uuid import uuid4

from backend.database import Database
from backend.models import Case, Evidence, Segment, SegmentStatus


def _make_case_and_evidence(db: Database) -> str:
    # A random suffix (not id(db)) avoids case_number collisions: CPython can
    # reuse an object's id() after it's garbage collected, which previously
    # caused a UNIQUE constraint clash with another test's case_number when
    # running the full suite (passed in isolation, failed in the full run).
    case = Case(case_number=f"DB-TEST-{uuid4()}", examiner="Det. Sharma")
    db.create_case(case)
    ev = Evidence(case_id=case.case_id, path="/tmp/fake.dd")
    db.save_evidence(ev)
    return ev.evidence_id


def test_delete_segments_for_evidence_removes_all_rows():
    db = Database()
    evidence_id = _make_case_and_evidence(db)

    seg1 = Segment(evidence_id=evidence_id, camera=0, status=SegmentStatus.PARTIAL)
    seg2 = Segment(evidence_id=evidence_id, camera=1, status=SegmentStatus.UNCERTAIN)
    db.save_segment(seg1)
    db.save_segment(seg2)
    assert len(db.list_segments_for_evidence(evidence_id)) == 2

    db.delete_segments_for_evidence(evidence_id)

    assert db.list_segments_for_evidence(evidence_id) == []


def test_delete_segments_for_evidence_also_clears_face_embeddings():
    from backend.face_search import FaceEmbeddingRecord

    db = Database()
    evidence_id = _make_case_and_evidence(db)

    seg = Segment(evidence_id=evidence_id, camera=0, status=SegmentStatus.PARTIAL)
    db.save_segment(seg)
    db.save_face_embeddings(seg.segment_id, [
        FaceEmbeddingRecord(frame_offset_seconds=1.0, bbox=[0, 0, 10, 10], embedding=[0.1, 0.2]),
    ])
    assert db.list_face_embeddings_for_segments([seg.segment_id]) != []

    db.delete_segments_for_evidence(evidence_id)

    assert db.list_face_embeddings_for_segments([seg.segment_id]) == []


def test_rescanning_evidence_replaces_rather_than_accumulates_segments():
    """
    Simulates what _run_scan does: label_all() produces fresh segment_ids
    every run, so main.py must clear old segments first. This reproduces the
    exact bug observed live (old Hikvision segments with stale notes text
    sitting alongside freshly-scanned ones after clicking "Re-Run Forensic
    Scan").
    """
    db = Database()
    evidence_id = _make_case_and_evidence(db)

    # First "scan"
    first_scan_segments = [
        Segment(evidence_id=evidence_id, camera=0, status=SegmentStatus.UNCERTAIN, notes="old scan"),
    ]
    for seg in first_scan_segments:
        db.save_segment(seg)
    assert len(db.list_segments_for_evidence(evidence_id)) == 1

    # Second "scan" — fresh segment_ids, as label_all() always generates
    second_scan_segments = [
        Segment(evidence_id=evidence_id, camera=0, status=SegmentStatus.PARTIAL, notes="new scan"),
        Segment(evidence_id=evidence_id, camera=1, status=SegmentStatus.PARTIAL, notes="new scan"),
    ]
    db.delete_segments_for_evidence(evidence_id)
    for seg in second_scan_segments:
        db.save_segment(seg)

    final = db.list_segments_for_evidence(evidence_id)
    assert len(final) == 2
    assert all(s.notes == "new scan" for s in final)
