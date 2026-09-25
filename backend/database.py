"""
database.py — SQLite persistence layer using the standard sqlite3 module.

One global database file lives at:
  {FORENSIC_CASE_DIR}/forensic.db

Exported files for each case live at:
  {FORENSIC_CASE_DIR}/{case_id}/exports/
  {FORENSIC_CASE_DIR}/{case_id}/reports/

All DB operations are synchronous; call them via asyncio.to_thread() from async contexts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from backend.secure_store import decrypt_text, encrypt_text
from backend.models import (
    AuditEntry,
    Case,
    Evidence,
    LogEvent,
    Segment,
    SegmentStatus,
)


class DuplicateCaseNumberError(Exception):
    """
    Raised by create_case() when case_number already exists.
    A shared exception type so callers (main.py) can catch one thing
    regardless of which Database backend (SQLite or Postgres) is active —
    the two backends' underlying drivers raise different, driver-specific
    integrity-error classes.
    """


def warn_if_onedrive(path: Path | str) -> Optional[str]:
    """Check if path contains OneDrive and return a warning string if true."""
    s = str(path).lower()
    if "onedrive" in s:
        warning = (
            f"WARNING: Case data path '{path}' is inside OneDrive! "
            "OneDrive cloud synchronization can alter file locks, corrupt SQLite databases, "
            "and violate evidence isolation protocols. Move case storage outside OneDrive (e.g. C:\\sih_cases)."
        )
        return warning
    return None


def _get_case_dir() -> Path:
    """
    Return the root directory for all case data.
    Configurable via the FORENSIC_CASE_DIR environment variable.
    Defaults to C:\\sih_cases (Windows) or ~/sih_cases (Linux/macOS), strictly outside OneDrive.
    """
    env = os.environ.get("FORENSIC_CASE_DIR", "")
    if env:
        d = Path(env)
    else:
        if os.name == "nt":
            d = Path("C:/sih_cases")
        else:
            d = Path.home() / "sih_cases"

    warn_msg = warn_if_onedrive(d)
    if warn_msg:
        import logging
        logging.getLogger("database").warning(warn_msg)
    return d


def get_case_dir() -> Path:
    return _get_case_dir()


def get_db_path() -> Path:
    return _get_case_dir() / "forensic.db"


def get_case_export_dir(case_id: str) -> Path:
    return _get_case_dir() / case_id / "exports"


def get_case_report_dir(case_id: str) -> Path:
    return _get_case_dir() / case_id / "reports"


def get_case_evidence_dir(case_id: str) -> Path:
    return _get_case_dir() / case_id / "evidence"


def get_case_accuracy_dir(case_id: str) -> Path:
    return _get_case_dir() / case_id / "accuracy"


def get_case_analysis_dir(case_id: str) -> Path:
    """Stored results of post-export analytics (object detection)."""
    return _get_case_dir() / case_id / "analysis"



# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    case_number TEXT NOT NULL UNIQUE,
    examiner    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    notes       TEXT
);

-- Idempotent: safe to run on existing databases that already have the index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_case_number ON cases(case_number);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id   TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    path          TEXT NOT NULL,
    size_bytes    INTEGER,
    sha256_before TEXT,
    md5_before    TEXT,
    sha256_after  TEXT,
    brand         TEXT,
    brand_version TEXT,
    confidence    REAL,
    is_synthetic  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
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
    motion_details    TEXT
);

CREATE TABLE IF NOT EXISTS log_events (
    event_id        TEXT PRIMARY KEY,
    evidence_id     TEXT NOT NULL,
    event_timestamp TEXT,
    event_type      TEXT,
    detail          TEXT,
    source_offset   INTEGER
);

CREATE TABLE IF NOT EXISTS audit_log (
    entry_id      TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    action        TEXT NOT NULL,
    details       TEXT,
    previous_hash TEXT,
    entry_hash    TEXT NOT NULL
);

-- Cached face embeddings for face similarity search (see backend/face_search.py).
-- Populated as a side effect of running face detection on a segment, so a
-- search doesn't have to re-decode every video every time.
CREATE TABLE IF NOT EXISTS face_embeddings (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id            TEXT NOT NULL,
    frame_offset_seconds  REAL,
    bbox_json             TEXT,
    embedding_json        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_segment ON face_embeddings(segment_id);

-- Single-examiner auth state (key-value store for password_hash and similar).
-- Only ever contains one row: key='password_hash', value=<bcrypt hash string>.
-- Plaintext passwords are NEVER stored here.
CREATE TABLE IF NOT EXISTS auth_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """Synchronous SQLite wrapper. Instantiate once and reuse."""

    def __init__(self) -> None:
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            try:
                conn.execute("ALTER TABLE segments ADD COLUMN motion_detected INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE segments ADD COLUMN motion_details TEXT")
            except Exception:
                pass
            try:
                # NULL case_id = global audit log (e.g. login/logout events).
                conn.execute("ALTER TABLE audit_log ADD COLUMN case_id TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN device_utc_offset_minutes INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE segments ADD COLUMN face_detected INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE segments ADD COLUMN face_detection_details TEXT")
            except Exception:
                pass

    # ── Cases ─────────────────────────────────────────────────────────────────

    def create_case(self, case: Case) -> Case:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO cases(case_id, case_number, examiner, created_at, notes) "
                    "VALUES (?,?,?,?,?)",
                    (case.case_id, case.case_number, case.examiner, case.created_at, case.notes),
                )
        except sqlite3.IntegrityError:
            raise DuplicateCaseNumberError(case.case_number)
        return case

    def get_case(self, case_id: str) -> Optional[Case]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE case_id=?", (case_id,)
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
                "INSERT OR REPLACE INTO evidence "
                "(evidence_id, case_id, path, size_bytes, sha256_before, md5_before, "
                " sha256_after, brand, brand_version, confidence, is_synthetic, created_at, "
                " device_utc_offset_minutes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                "SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_synthetic"] = bool(d["is_synthetic"])
        return Evidence(**d)

    def list_evidence_for_case(self, case_id: str) -> list[Evidence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE case_id=? ORDER BY created_at ASC, evidence_id ASC",
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
                "INSERT OR REPLACE INTO segments "
                "(segment_id, evidence_id, camera, start_time, end_time, "
                " disk_offsets_json, frame_count, status, export_path, sha256, notes, "
                " motion_detected, motion_details, face_detected, face_detection_details) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                "SELECT segment_id FROM segments WHERE evidence_id=?", (evidence_id,)
            ).fetchall()
            segment_ids = [r["segment_id"] for r in rows]
            if segment_ids:
                placeholders = ",".join("?" for _ in segment_ids)
                conn.execute(
                    f"DELETE FROM face_embeddings WHERE segment_id IN ({placeholders})",
                    segment_ids,
                )
            conn.execute("DELETE FROM segments WHERE evidence_id=?", (evidence_id,))

    def list_segments_for_evidence(self, evidence_id: str) -> list[Segment]:
        from backend.models import DiskOffset
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE evidence_id=? ORDER BY camera, start_time",
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
            # Parse datetimes
            from datetime import datetime, timezone
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
            conn.execute("DELETE FROM face_embeddings WHERE segment_id=?", (segment_id,))
            conn.executemany(
                "INSERT INTO face_embeddings "
                "(segment_id, frame_offset_seconds, bbox_json, embedding_json) "
                "VALUES (?,?,?,?)",
                [
                    (
                        segment_id,
                        r.frame_offset_seconds,
                        json.dumps(r.bbox),
                        encrypt_text(json.dumps(r.embedding)),   # biometric template: encrypted at rest
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
        placeholders = ",".join("?" for _ in segment_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT segment_id, frame_offset_seconds, bbox_json, embedding_json "
                f"FROM face_embeddings WHERE segment_id IN ({placeholders})",
                segment_ids,
            ).fetchall()
        return [
            {
                "segment_id": r["segment_id"],
                "frame_offset_seconds": r["frame_offset_seconds"],
                "bbox": json.loads(r["bbox_json"] or "[]"),
                "embedding": json.loads(decrypt_text(r["embedding_json"])),
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
                "INSERT OR REPLACE INTO audit_log "
                "(entry_id, case_id, created_at, action, details, previous_hash, entry_hash) "
                "VALUES (?,?,?,?,?,?,?)",
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
                    "FROM audit_log WHERE case_id=? ORDER BY created_at",
                    (case_id,),
                ).fetchall()
        return [AuditEntry(**dict(r)) for r in rows]

    # ── Log events ────────────────────────────────────────────────────────────

    def save_log_event(self, event: LogEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO log_events "
                "(event_id, evidence_id, event_timestamp, event_type, detail, source_offset) "
                "VALUES (?,?,?,?,?,?)",
                (
                    event.event_id, event.evidence_id,
                    event.event_timestamp.isoformat() if event.event_timestamp else None,
                    event.event_type, event.detail, event.source_offset,
                ),
            )

    def list_log_events(self, evidence_id: str) -> list[LogEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM log_events WHERE evidence_id=? ORDER BY event_timestamp",
                (evidence_id,),
            ).fetchall()
        return [LogEvent(**dict(r)) for r in rows]

    # ── Auth state ─────────────────────────────────────────────────────────────

    def get_auth_value(self, key: str) -> Optional[str]:
        """Return the stored value for key, or None if not set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM auth_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_auth_value(self, key: str, value: str) -> None:
        """Upsert key → value in auth_state.  Used only for the bcrypt hash."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO auth_state(key, value) VALUES (?,?)",
                (key, value),
            )

