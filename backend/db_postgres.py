"""
db_postgres.py — Postgres (Supabase) persistence layer, mirroring database.py's
Database class method-for-method so backend/main.py never needs to know or
care which backend is active (see _create_database() in main.py).

Uses psycopg2 (a synchronous driver, like sqlite3) rather than an async driver
(e.g. asyncpg) specifically so this class can be called the exact same way as
the SQLite Database class: synchronously, wrapped in asyncio.to_thread() from
async route handlers. A connection pool (not a single shared connection) is
used because opening a fresh network connection to a remote Postgres instance
per call — unlike SQLite's cheap local file connections — would be slow and
would not scale to concurrent requests.

Exported files for each case still live on local disk (see get_case_export_dir/
get_case_report_dir in database.py) regardless of which DB backend is active —
only structured case/evidence/segment/audit records move to Postgres.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

from backend.database import DuplicateCaseNumberError
from backend.models import (
    AuditEntry,
    Case,
    Evidence,
    LogEvent,
    Segment,
    SegmentStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    case_number TEXT NOT NULL UNIQUE,
    examiner    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id   TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    path          TEXT NOT NULL,
    size_bytes    BIGINT,
    sha256_before TEXT,
    md5_before    TEXT,
    sha256_after  TEXT,
    brand         TEXT,
    brand_version TEXT,
    confidence    DOUBLE PRECISION,
    is_synthetic  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    device_utc_offset_minutes INTEGER
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id        TEXT PRIMARY KEY,
    evidence_id       TEXT NOT NULL REFERENCES evidence(evidence_id),
    camera            INTEGER NOT NULL,
    start_time        TEXT,
    end_time          TEXT,
    disk_offsets_json TEXT,
    frame_count       INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL,
    export_path       TEXT,
    sha256            TEXT,
    notes             TEXT,
    motion_detected   INTEGER,
    motion_details    TEXT,
    face_detected     INTEGER,
    face_detection_details TEXT
);

CREATE TABLE IF NOT EXISTS log_events (
    event_id        TEXT PRIMARY KEY,
    evidence_id     TEXT NOT NULL,
    event_timestamp TEXT,
    event_type      TEXT,
    detail          TEXT,
    source_offset   BIGINT
);

CREATE TABLE IF NOT EXISTS audit_log (
    entry_id      TEXT PRIMARY KEY,
    case_id       TEXT,
    created_at    TEXT NOT NULL,
    action        TEXT NOT NULL,
    details       TEXT,
    previous_hash TEXT,
    entry_hash    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    id                    SERIAL PRIMARY KEY,
    segment_id            TEXT NOT NULL,
    frame_offset_seconds  DOUBLE PRECISION,
    bbox_json             TEXT,
    embedding_json        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_segment ON face_embeddings(segment_id);

CREATE TABLE IF NOT EXISTS auth_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class _CursorWrapper:
    """
    Thin shim so call sites can do conn.execute(...) / conn.executemany(...)
    exactly like sqlite3.Connection allows, instead of psycopg2's
    conn.cursor().execute(...). Keeps this file's method bodies close to
    database.py's for easier side-by-side review.
    """

    def __init__(self, pg_conn) -> None:
        self._conn = pg_conn

    def execute(self, sql: str, params: tuple = ()) -> "psycopg2.extensions.cursor":
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq_of_params) -> None:
        cur = self._conn.cursor()
        cur.executemany(sql, seq_of_params)

    def executescript(self, sql: str) -> None:
        cur = self._conn.cursor()
        cur.execute(sql)


class PostgresDatabase:
    """Synchronous Postgres (Supabase) wrapper. Instantiate once and reuse."""

    def __init__(self, database_url: str, minconn: int = 1, maxconn: int = 10) -> None:
        # Descriptive, password-free string — used only for startup logging,
        # and so main.py's hasattr(db, "_path") backend-agnostic check works.
        parsed = urlsplit(database_url)
        self._path = f"postgres://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"

        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn, dsn=database_url, sslmode="require",
        )
        self._init_schema()

    @contextmanager
    def _connect(self):
        pg_conn = self._pool.getconn()
        try:
            yield _CursorWrapper(pg_conn)
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()
            raise
        finally:
            self._pool.putconn(pg_conn)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── Cases ─────────────────────────────────────────────────────────────────

    def create_case(self, case: Case) -> Case:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO cases(case_id, case_number, examiner, created_at, notes) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (case.case_id, case.case_number, case.examiner, case.created_at, case.notes),
                )
        except psycopg2.errors.UniqueViolation:
            raise DuplicateCaseNumberError(case.case_number)
        return case

    def get_case(self, case_id: str) -> Optional[Case]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE case_id=%s", (case_id,)
            ).fetchone()
        return Case(**dict(row)) if row else None

    def list_cases(self) -> list[Case]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
        return [Case(**dict(r)) for r in rows]

    # ── Evidence ──────────────────────────────────────────────────────────────

    def save_evidence(self, ev: Evidence) -> Evidence:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evidence "
                "(evidence_id, case_id, path, size_bytes, sha256_before, md5_before, "
                " sha256_after, brand, brand_version, confidence, is_synthetic, created_at, "
                " device_utc_offset_minutes) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (evidence_id) DO UPDATE SET "
                "  case_id=EXCLUDED.case_id, path=EXCLUDED.path, size_bytes=EXCLUDED.size_bytes, "
                "  sha256_before=EXCLUDED.sha256_before, md5_before=EXCLUDED.md5_before, "
                "  sha256_after=EXCLUDED.sha256_after, brand=EXCLUDED.brand, "
                "  brand_version=EXCLUDED.brand_version, confidence=EXCLUDED.confidence, "
                "  is_synthetic=EXCLUDED.is_synthetic, created_at=EXCLUDED.created_at, "
                "  device_utc_offset_minutes=EXCLUDED.device_utc_offset_minutes",
                (
                    ev.evidence_id, ev.case_id, ev.path, ev.size_bytes,
                    ev.sha256_before, ev.md5_before, ev.sha256_after,
                    ev.brand, ev.brand_version, ev.confidence,
                    int(ev.is_synthetic), ev.created_at,
                    ev.device_utc_offset_minutes,
                ),
            )
        return ev

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id=%s", (evidence_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_synthetic"] = bool(d["is_synthetic"])
        return Evidence(**d)

    def list_evidence_for_case(self, case_id: str) -> list[Evidence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE case_id=%s ORDER BY created_at ASC, evidence_id ASC",
                (case_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["is_synthetic"] = bool(d["is_synthetic"])
            result.append(Evidence(**d))
        return result

    # ── Segments ──────────────────────────────────────────────────────────────

    def save_segment(self, seg: Segment) -> Segment:
        offsets_json = json.dumps([o.model_dump() for o in seg.disk_offsets])
        motion_int = int(seg.motion_detected) if seg.motion_detected is not None else None
        face_int = int(seg.face_detected) if seg.face_detected is not None else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO segments "
                "(segment_id, evidence_id, camera, start_time, end_time, "
                " disk_offsets_json, frame_count, status, export_path, sha256, notes, "
                " motion_detected, motion_details, face_detected, face_detection_details) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (segment_id) DO UPDATE SET "
                "  evidence_id=EXCLUDED.evidence_id, camera=EXCLUDED.camera, "
                "  start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time, "
                "  disk_offsets_json=EXCLUDED.disk_offsets_json, frame_count=EXCLUDED.frame_count, "
                "  status=EXCLUDED.status, export_path=EXCLUDED.export_path, sha256=EXCLUDED.sha256, "
                "  notes=EXCLUDED.notes, motion_detected=EXCLUDED.motion_detected, "
                "  motion_details=EXCLUDED.motion_details, face_detected=EXCLUDED.face_detected, "
                "  face_detection_details=EXCLUDED.face_detection_details",
                (
                    seg.segment_id, seg.evidence_id, seg.camera,
                    seg.start_time.isoformat() if seg.start_time else None,
                    seg.end_time.isoformat() if seg.end_time else None,
                    offsets_json,
                    seg.frame_count, seg.status.value,
                    seg.export_path, seg.sha256, seg.notes,
                    motion_int, seg.motion_details,
                    face_int, seg.face_detection_details,
                ),
            )
        return seg

    def delete_segments_for_evidence(self, evidence_id: str) -> None:
        """
        Remove all segments (and their cached face embeddings) for one
        evidence item. Called before saving a fresh scan's segments so
        re-running a scan replaces the previous results instead of
        accumulating duplicate, contradictory segment rows alongside them.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT segment_id FROM segments WHERE evidence_id=%s", (evidence_id,)
            ).fetchall()
            segment_ids = [r["segment_id"] for r in rows]
            if segment_ids:
                conn.execute(
                    "DELETE FROM face_embeddings WHERE segment_id = ANY(%s)",
                    (segment_ids,),
                )
            conn.execute("DELETE FROM segments WHERE evidence_id=%s", (evidence_id,))

    def list_segments_for_evidence(self, evidence_id: str) -> list[Segment]:
        from backend.models import DiskOffset
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE evidence_id=%s ORDER BY camera, start_time",
                (evidence_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["disk_offsets"] = [
                DiskOffset(**o) for o in json.loads(d.pop("disk_offsets_json") or "[]")
            ]
            d["status"] = SegmentStatus(d["status"])
            if "motion_detected" in d and d["motion_detected"] is not None:
                d["motion_detected"] = bool(d["motion_detected"])
            if "face_detected" in d and d["face_detected"] is not None:
                d["face_detected"] = bool(d["face_detected"])
            for key in ("start_time", "end_time"):
                if d[key]:
                    d[key] = datetime.fromisoformat(d[key])
            result.append(Segment(**d))
        return result

    # ── Face embeddings (face similarity search) ─────────────────────────────

    def save_face_embeddings(self, segment_id: str, records: list) -> None:
        """
        Replace all cached face embeddings for one segment with *records*
        (a list of face_search.FaceEmbeddingRecord). Called after re-running
        face detection so stale embeddings from a previous export don't linger.
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM face_embeddings WHERE segment_id=%s", (segment_id,))
            conn.executemany(
                "INSERT INTO face_embeddings "
                "(segment_id, frame_offset_seconds, bbox_json, embedding_json) "
                "VALUES (%s,%s,%s,%s)",
                [
                    (
                        segment_id,
                        r.frame_offset_seconds,
                        json.dumps(r.bbox),
                        json.dumps(r.embedding),
                    )
                    for r in records
                ],
            )

    def list_face_embeddings_for_segments(self, segment_ids: list[str]) -> list[dict]:
        """
        Return cached face embeddings for the given segment ids, as dicts:
        {segment_id, frame_offset_seconds, bbox, embedding}.
        """
        if not segment_ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT segment_id, frame_offset_seconds, bbox_json, embedding_json "
                "FROM face_embeddings WHERE segment_id = ANY(%s)",
                (segment_ids,),
            ).fetchall()
        return [
            {
                "segment_id": r["segment_id"],
                "frame_offset_seconds": r["frame_offset_seconds"],
                "bbox": json.loads(r["bbox_json"] or "[]"),
                "embedding": json.loads(r["embedding_json"]),
            }
            for r in rows
        ]

    # ── Audit log ─────────────────────────────────────────────────────────────

    def save_audit_entry(self, entry: AuditEntry, case_id: Optional[str] = None) -> None:
        """
        Persist one audit entry. *case_id* is None for global (non-case) events
        such as login/logout; otherwise scopes the entry to one case.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log "
                "(entry_id, case_id, created_at, action, details, previous_hash, entry_hash) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (entry_id) DO UPDATE SET "
                "  case_id=EXCLUDED.case_id, created_at=EXCLUDED.created_at, "
                "  action=EXCLUDED.action, details=EXCLUDED.details, "
                "  previous_hash=EXCLUDED.previous_hash, entry_hash=EXCLUDED.entry_hash",
                (
                    entry.entry_id, case_id, entry.created_at, entry.action,
                    entry.details, entry.previous_hash, entry.entry_hash,
                ),
            )

    def load_audit_entries(self, case_id: Optional[str] = None) -> list[AuditEntry]:
        """
        Return persisted audit entries in chain order.
        *case_id* is None to load the global (login/logout) audit log, or a
        case id to load that case's entries only.
        """
        with self._connect() as conn:
            if case_id is None:
                rows = conn.execute(
                    "SELECT entry_id, created_at, action, details, previous_hash, entry_hash "
                    "FROM audit_log WHERE case_id IS NULL ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT entry_id, created_at, action, details, previous_hash, entry_hash "
                    "FROM audit_log WHERE case_id=%s ORDER BY created_at",
                    (case_id,),
                ).fetchall()
        return [AuditEntry(**dict(r)) for r in rows]

    # ── Log events ────────────────────────────────────────────────────────────

    def save_log_event(self, event: LogEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO log_events "
                "(event_id, evidence_id, event_timestamp, event_type, detail, source_offset) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (event_id) DO UPDATE SET "
                "  evidence_id=EXCLUDED.evidence_id, event_timestamp=EXCLUDED.event_timestamp, "
                "  event_type=EXCLUDED.event_type, detail=EXCLUDED.detail, "
                "  source_offset=EXCLUDED.source_offset",
                (
                    event.event_id, event.evidence_id,
                    event.event_timestamp.isoformat() if event.event_timestamp else None,
                    event.event_type, event.detail, event.source_offset,
                ),
            )

    def list_log_events(self, evidence_id: str) -> list[LogEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM log_events WHERE evidence_id=%s ORDER BY event_timestamp",
                (evidence_id,),
            ).fetchall()
        return [LogEvent(**dict(r)) for r in rows]

    # ── Auth state ─────────────────────────────────────────────────────────────

    def get_auth_value(self, key: str) -> Optional[str]:
        """Return the stored value for key, or None if not set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM auth_state WHERE key=%s", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_auth_value(self, key: str, value: str) -> None:
        """Upsert key -> value in auth_state. Used only for the bcrypt hash."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_state(key, value) VALUES (%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                (key, value),
            )
