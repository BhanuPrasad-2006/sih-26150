"""
db_supabase_client.py — Supabase client-key database backend.

Used by the desktop installer build. Connects to Supabase via the supabase-py
client library using the project URL + anon key — both client-safe credentials
that can be embedded in a desktop/mobile app. The Postgres password is never
required or used.

Row Level Security (RLS) on the Supabase project controls what the anon key
can do. All forensic evidence files remain on the user's local disk and are
never sent to Supabase.

Method signatures mirror db_postgres.PostgresDatabase exactly so main.py's
_create_database() can swap backends transparently.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from datetime import datetime
from typing import Optional

log = logging.getLogger("db_supabase_client")


def _require_supabase():
    try:
        from supabase import create_client, Client  # noqa: F401
        return create_client, Client
    except ImportError as exc:
        raise RuntimeError(
            "The 'supabase' package is required for the desktop build. "
            "Run: pip install supabase"
        ) from exc


class SupabaseDatabase:
    """
    Supabase REST (PostgREST) database backend.

    Uses the public anon key — safe to bundle in the installer.
    The Postgres connection password is never used here.
    """

    def __init__(self, supabase_url: str, anon_key: str) -> None:
        create_client, _ = _require_supabase()
        self._client = create_client(supabase_url, anon_key)
        # Descriptive identifier for logging (no credentials)
        self._path = f"supabase://{supabase_url.rstrip('/').rsplit('/', 1)[-1]}"
        log.info("Supabase client initialised: %s", self._path)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _table(self, name: str):
        """Return a supabase-py table query builder."""
        return self._client.table(name)

    # ── Cases ─────────────────────────────────────────────────────────────────

    def create_case(self, case) -> object:
        from backend.database import DuplicateCaseNumberError
        data = {
            "case_id": case.case_id,
            "case_number": case.case_number,
            "case_title": getattr(case, "case_title", None),
            "created_by": getattr(case, "created_by", None),
            "examiner": case.examiner,
            "agency": getattr(case, "agency", None),
            "fir_number": getattr(case, "fir_number", None),
            "incident_date": getattr(case, "incident_date", None),
            "seizure_officer": getattr(case, "seizure_officer", None),
            "seizure_location": getattr(case, "seizure_location", None),
            "priority": getattr(case, "priority", "MEDIUM"),
            "status": getattr(case, "status", "ACTIVE"),
            "target_device": getattr(case, "target_device", None),
            "created_at": case.created_at,
            "updated_at": getattr(case, "updated_at", None),
            "notes": case.notes,
        }
        try:
            self._table("cases").insert(data).execute()
        except Exception as exc:
            # PostgREST returns a 409/23505 on unique constraint violation
            if "23505" in str(exc) or "duplicate" in str(exc).lower():
                from backend.database import DuplicateCaseNumberError
                raise DuplicateCaseNumberError(case.case_number) from exc
            raise
        return case

    def get_case(self, case_id: str) -> Optional[object]:
        from backend.models import Case
        res = self._table("cases").select("*").eq("case_id", case_id).limit(1).execute()
        if not res.data:
            return None
        return Case(**res.data[0])

    def list_cases(self, examiner: Optional[str] = None) -> list:
        from backend.models import Case
        query = self._table("cases").select("*").order("created_at", desc=True)
        if examiner:
            query = query.or_(f"created_by.eq.{examiner},examiner.eq.{examiner}")
        res = query.execute()
        return [Case(**r) for r in (res.data or [])]

    # ── Evidence ──────────────────────────────────────────────────────────────

    def save_evidence(self, ev) -> object:
        data = {
            "evidence_id": ev.evidence_id,
            "case_id": ev.case_id,
            "path": ev.path,
            "device_type": getattr(ev, "device_type", None),
            "make_model": getattr(ev, "make_model", None),
            "serial_number": getattr(ev, "serial_number", None),
            "capacity": getattr(ev, "capacity", None),
            "write_blocker": getattr(ev, "write_blocker", None),
            "evidence_tag": getattr(ev, "evidence_tag", None),
            "size_bytes": ev.size_bytes,
            "sha256_before": ev.sha256_before,
            "md5_before": ev.md5_before,
            "sha256_after": ev.sha256_after,
            "brand": ev.brand,
            "brand_version": ev.brand_version,
            "confidence": ev.confidence,
            "is_synthetic": int(ev.is_synthetic),
            "created_at": ev.created_at,
            "device_utc_offset_minutes": ev.device_utc_offset_minutes,
        }
        self._table("evidence").upsert(data).execute()
        return ev

    def get_evidence(self, evidence_id: str) -> Optional[object]:
        from backend.models import Evidence
        res = (
            self._table("evidence")
            .select("*")
            .eq("evidence_id", evidence_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        d = res.data[0].copy()
        d["is_synthetic"] = bool(d.get("is_synthetic"))
        return Evidence(**d)

    def list_evidence_for_case(self, case_id: str) -> list:
        from backend.models import Evidence
        res = (
            self._table("evidence")
            .select("*")
            .eq("case_id", case_id)
            .order("created_at")
            .order("evidence_id")
            .execute()
        )
        result = []
        for r in (res.data or []):
            d = r.copy()
            d["is_synthetic"] = bool(d.get("is_synthetic"))
            result.append(Evidence(**d))
        return result

    # ── Segments ──────────────────────────────────────────────────────────────

    def save_segment(self, seg) -> object:
        from backend.models import DiskOffset
        motion_int = int(seg.motion_detected) if seg.motion_detected is not None else None
        face_int = int(seg.face_detected) if seg.face_detected is not None else None
        data = {
            "segment_id": seg.segment_id,
            "evidence_id": seg.evidence_id,
            "camera": seg.camera,
            "start_time": seg.start_time.isoformat() if seg.start_time else None,
            "end_time": seg.end_time.isoformat() if seg.end_time else None,
            "disk_offsets_json": json.dumps([o.model_dump() for o in seg.disk_offsets]),
            "frame_count": seg.frame_count,
            "status": seg.status.value,
            "export_path": seg.export_path,
            "sha256": seg.sha256,
            "notes": seg.notes,
            "motion_detected": motion_int,
            "motion_details": seg.motion_details,
            "face_detected": face_int,
            "face_detection_details": seg.face_detection_details,
        }
        self._table("segments").upsert(data).execute()
        return seg

    def delete_segments_for_evidence(self, evidence_id: str) -> None:
        # Delete associated face embeddings first (via segment IDs)
        seg_res = (
            self._table("segments")
            .select("segment_id")
            .eq("evidence_id", evidence_id)
            .execute()
        )
        seg_ids = [r["segment_id"] for r in (seg_res.data or [])]
        if seg_ids:
            for sid in seg_ids:
                self._table("face_embeddings").delete().eq("segment_id", sid).execute()
        self._table("segments").delete().eq("evidence_id", evidence_id).execute()

    def list_segments_for_evidence(self, evidence_id: str) -> list:
        from backend.models import DiskOffset, Segment, SegmentStatus
        res = (
            self._table("segments")
            .select("*")
            .eq("evidence_id", evidence_id)
            .order("camera")
            .order("start_time")
            .execute()
        )
        result = []
        for r in (res.data or []):
            d = r.copy()
            d["disk_offsets"] = [
                DiskOffset(**o) for o in json.loads(d.pop("disk_offsets_json") or "[]")
            ]
            d["status"] = SegmentStatus(d["status"])
            if d.get("motion_detected") is not None:
                d["motion_detected"] = bool(d["motion_detected"])
            if d.get("face_detected") is not None:
                d["face_detected"] = bool(d["face_detected"])
            for key in ("start_time", "end_time"):
                if d.get(key):
                    d[key] = datetime.fromisoformat(d[key])
            result.append(Segment(**d))
        return result

    # ── Face embeddings ───────────────────────────────────────────────────────

    def save_face_embeddings(self, segment_id: str, records: list) -> None:
        from backend.secure_store import encrypt_text
        self._table("face_embeddings").delete().eq("segment_id", segment_id).execute()
        rows = [
            {
                "segment_id": segment_id,
                "frame_offset_seconds": r.frame_offset_seconds,
                "bbox_json": json.dumps(r.bbox),
                "embedding_json": encrypt_text(json.dumps(r.embedding)),
            }
            for r in records
        ]
        if rows:
            self._table("face_embeddings").insert(rows).execute()

    def list_face_embeddings_for_segments(self, segment_ids: list[str]) -> list[dict]:
        from backend.secure_store import decrypt_text
        if not segment_ids:
            return []
        # PostgREST IN filter
        res = (
            self._table("face_embeddings")
            .select("segment_id, frame_offset_seconds, bbox_json, embedding_json")
            .in_("segment_id", segment_ids)
            .execute()
        )
        return [
            {
                "segment_id": r["segment_id"],
                "frame_offset_seconds": r["frame_offset_seconds"],
                "bbox": json.loads(r.get("bbox_json") or "[]"),
                "embedding": json.loads(decrypt_text(r["embedding_json"])),
            }
            for r in (res.data or [])
        ]

    # ── Audit log ─────────────────────────────────────────────────────────────

    def save_audit_entry(self, entry, case_id: Optional[str] = None) -> None:
        data = {
            "entry_id": entry.entry_id,
            "case_id": case_id,
            "created_at": entry.created_at,
            "action": entry.action,
            "details": entry.details,
            "previous_hash": entry.previous_hash,
            "entry_hash": entry.entry_hash,
        }
        self._table("audit_log").upsert(data).execute()

    def load_audit_entries(self, case_id: Optional[str] = None) -> list:
        from backend.models import AuditEntry
        q = self._table("audit_log").select(
            "entry_id, created_at, action, details, previous_hash, entry_hash"
        ).order("created_at")
        if case_id is None:
            q = q.is_("case_id", "null")
        else:
            q = q.eq("case_id", case_id)
        res = q.execute()
        return [AuditEntry(**r) for r in (res.data or [])]

    # ── Log events ────────────────────────────────────────────────────────────

    def save_log_event(self, event) -> None:
        data = {
            "event_id": event.event_id,
            "evidence_id": event.evidence_id,
            "event_timestamp": (
                event.event_timestamp.isoformat() if event.event_timestamp else None
            ),
            "event_type": event.event_type,
            "detail": event.detail,
            "source_offset": event.source_offset,
        }
        self._table("log_events").upsert(data).execute()

    def list_log_events(self, evidence_id: str) -> list:
        from backend.models import LogEvent
        res = (
            self._table("log_events")
            .select("*")
            .eq("evidence_id", evidence_id)
            .order("event_timestamp")
            .execute()
        )
        return [LogEvent(**r) for r in (res.data or [])]

    # ── Auth state ────────────────────────────────────────────────────────────

    def get_auth_value(self, key: str) -> Optional[str]:
        res = (
            self._table("auth_state")
            .select("value")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("value")
        return None

    def set_auth_value(self, key: str, value: str) -> None:
        self._table("auth_state").upsert({"key": key, "value": value}).execute()
        if key == "users":
            try:
                import json
                users = json.loads(value)
                for uname, udata in users.items():
                    display_name = udata.get("username", uname)
                    self._table("users").upsert({
                        "username": display_name,
                        "password_hash": udata.get("password_hash"),
                        "totp_secret": udata.get("totp_secret"),
                        "totp_recovery": udata.get("totp_recovery"),
                        "failure_count": udata.get("failure_count", 0),
                        "lockout_until": udata.get("lockout_until", 0.0),
                    }, on_conflict="username").execute()
            except Exception:
                pass
