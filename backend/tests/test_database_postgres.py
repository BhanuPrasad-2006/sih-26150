"""
test_database_postgres.py — Integration tests for PostgresDatabase against a
real Supabase/Postgres instance.

These are intentionally NOT part of the default isolated suite's blast radius:
conftest.py forces DATABASE_URL="" for the whole session (see its ISOLATION
GUARANTEE note) specifically so the other 80+ tests never touch a live cloud
database. This file instead reads the connection string directly out of a
.env file via dotenv_values() — which does NOT touch os.environ — so it never
fights conftest's override and never leaks a live DB into any other test.

Skips cleanly (does not fail) when no .env / DATABASE_URL is available, e.g.
on a machine or CI runner with no Supabase access configured.

Every test cleans up the rows it creates, since this runs against a real,
shared, persistent database rather than a disposable temp file.
"""

from __future__ import annotations

import uuid

import pytest
from dotenv import dotenv_values

_env = dotenv_values(".env")
_DATABASE_URL = _env.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="No DATABASE_URL in .env — skipping live Postgres/Supabase integration tests.",
)

if _DATABASE_URL:
    from backend.database import DuplicateCaseNumberError
    from backend.db_postgres import PostgresDatabase
    from backend.face_search import FaceEmbeddingRecord
    from backend.models import AuditEntry, Case, Evidence, Segment, SegmentStatus


@pytest.fixture(scope="module")
def pg_db():
    return PostgresDatabase(_DATABASE_URL)


@pytest.fixture
def case_and_evidence(pg_db):
    """A case + evidence row scoped to this test, cleaned up afterward."""
    suffix = uuid.uuid4().hex[:12]
    case = Case(case_number=f"PGTEST-{suffix}", examiner="Det. Sharma")
    pg_db.create_case(case)
    ev = Evidence(case_id=case.case_id, path=f"/tmp/pgtest-{suffix}.dd")
    pg_db.save_evidence(ev)

    yield case, ev

    with pg_db._connect() as conn:
        conn.execute("DELETE FROM segments WHERE evidence_id=%s", (ev.evidence_id,))
        conn.execute("DELETE FROM evidence WHERE evidence_id=%s", (ev.evidence_id,))
        conn.execute("DELETE FROM cases WHERE case_id=%s", (case.case_id,))


def test_create_and_get_case_round_trip(pg_db, case_and_evidence):
    case, _ = case_and_evidence
    fetched = pg_db.get_case(case.case_id)
    assert fetched is not None
    assert fetched.case_number == case.case_number
    assert fetched.examiner == "Det. Sharma"


def test_list_cases_includes_created_case(pg_db, case_and_evidence):
    case, _ = case_and_evidence
    all_cases = pg_db.list_cases()
    assert any(c.case_id == case.case_id for c in all_cases)


def test_duplicate_case_number_raises(pg_db, case_and_evidence):
    case, _ = case_and_evidence
    dupe = Case(case_number=case.case_number, examiner="Someone Else")
    with pytest.raises(DuplicateCaseNumberError):
        pg_db.create_case(dupe)


def test_evidence_round_trip_and_offset(pg_db, case_and_evidence):
    case, ev = case_and_evidence
    ev.brand = "Dahua"
    ev.confidence = 0.95
    ev.device_utc_offset_minutes = 330
    pg_db.save_evidence(ev)

    fetched = pg_db.get_evidence(ev.evidence_id)
    assert fetched.brand == "Dahua"
    assert fetched.confidence == pytest.approx(0.95)
    assert fetched.device_utc_offset_minutes == 330

    for_case = pg_db.list_evidence_for_case(case.case_id)
    assert len(for_case) == 1
    assert for_case[0].evidence_id == ev.evidence_id


def test_segment_save_list_and_delete(pg_db, case_and_evidence):
    _, ev = case_and_evidence
    seg = Segment(evidence_id=ev.evidence_id, camera=0, status=SegmentStatus.PARTIAL, notes="pg test")
    pg_db.save_segment(seg)

    segs = pg_db.list_segments_for_evidence(ev.evidence_id)
    assert len(segs) == 1
    assert segs[0].notes == "pg test"
    assert segs[0].status == SegmentStatus.PARTIAL

    # Re-saving with the same segment_id must update in place (ON CONFLICT), not duplicate.
    seg.notes = "updated"
    pg_db.save_segment(seg)
    segs = pg_db.list_segments_for_evidence(ev.evidence_id)
    assert len(segs) == 1
    assert segs[0].notes == "updated"

    pg_db.delete_segments_for_evidence(ev.evidence_id)
    assert pg_db.list_segments_for_evidence(ev.evidence_id) == []


def test_face_embeddings_round_trip_and_cleanup_on_segment_delete(pg_db, case_and_evidence):
    _, ev = case_and_evidence
    seg = Segment(evidence_id=ev.evidence_id, camera=0, status=SegmentStatus.PARTIAL)
    pg_db.save_segment(seg)

    pg_db.save_face_embeddings(seg.segment_id, [
        FaceEmbeddingRecord(frame_offset_seconds=1.5, bbox=[0, 0, 10, 10], embedding=[0.1, 0.2, 0.3]),
    ])
    records = pg_db.list_face_embeddings_for_segments([seg.segment_id])
    assert len(records) == 1
    assert records[0]["embedding"] == [0.1, 0.2, 0.3]

    # Deleting the segment must also clear its cached embeddings.
    pg_db.delete_segments_for_evidence(ev.evidence_id)
    assert pg_db.list_face_embeddings_for_segments([seg.segment_id]) == []


def test_audit_entries_scoped_by_case_and_global(pg_db, case_and_evidence):
    case, _ = case_and_evidence
    entry = AuditEntry(action="scan_started", details="test", entry_hash="abc123")
    pg_db.save_audit_entry(entry, case_id=case.case_id)

    global_entry = AuditEntry(action="login", details="", entry_hash="def456")
    pg_db.save_audit_entry(global_entry, case_id=None)

    case_entries = pg_db.load_audit_entries(case_id=case.case_id)
    assert any(e.entry_id == entry.entry_id for e in case_entries)
    assert not any(e.entry_id == global_entry.entry_id for e in case_entries)

    global_entries = pg_db.load_audit_entries(case_id=None)
    assert any(e.entry_id == global_entry.entry_id for e in global_entries)

    with pg_db._connect() as conn:
        conn.execute("DELETE FROM audit_log WHERE entry_id IN (%s, %s)", (entry.entry_id, global_entry.entry_id))


def test_auth_value_upsert(pg_db):
    key = f"pgtest_key_{uuid.uuid4().hex[:8]}"
    assert pg_db.get_auth_value(key) is None

    pg_db.set_auth_value(key, "value-one")
    assert pg_db.get_auth_value(key) == "value-one"

    pg_db.set_auth_value(key, "value-two")
    assert pg_db.get_auth_value(key) == "value-two"

    with pg_db._connect() as conn:
        conn.execute("DELETE FROM auth_state WHERE key=%s", (key,))
