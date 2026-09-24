"""
main.py — FastAPI application entry point.

Binds ONLY to 127.0.0.1 (localhost). No external access. No telemetry.
Serves the frontend at / and API at /api.

Authentication:
  Every /api/* route requires a valid sih_session cookie EXCEPT:
    GET  /api/auth/status   — lets the frontend discover auth state on load
    POST /api/auth/login    — the login endpoint itself
    POST /api/auth/setup    — first-run password creation
  These are enforced by AuthMiddleware at the Starlette level, so every
  current and future route is automatically protected.

Scan flow:
  POST /api/cases/{id}/evidence  → load image, hash, store evidence record
  POST /api/cases/{id}/scan      → start background scan task (async)
  GET  /api/cases/{id}/status    → SSE stream of ScanProgress events
  GET  /api/cases/{id}/segments  → list recovered segments
  POST /api/cases/{id}/export/{seg_id} → export one segment to MP4
  GET  /api/cases/{id}/verify    → re-hash evidence, compare
  GET  /api/cases/{id}/report    → generate PDF and return it
  GET  /api/cases/{id}/audit     → return full audit log as JSON
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from uuid import uuid4
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import aiofiles
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

# Load .env (if present) before anything reads DATABASE_URL/PG* env vars.
# A no-op when no .env file exists, so this is safe on any deployment target.
load_dotenv()

from backend.acquisition import AcquisitionError, EvidenceImage, verify_disk_image_integrity
from backend.audit import AuditLog
from backend.auth import AuthManager
from backend.database import (
    Database,
    DuplicateCaseNumberError,
    get_case_accuracy_dir,
    get_case_analysis_dir,
    get_case_evidence_dir,
    get_case_export_dir,
    get_case_report_dir,
)
from backend.exporter import export_segment
from backend.motion import detect_motion_in_video
from backend.models import (
    AuditEntry,
    Case,
    CaseDetail,
    Evidence,
    RawFrame,
    ScanPhase,
    ScanProgress,
    Segment,
    SegmentStatus,
)
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE
from backend.plugins.cpplus import CPPlusPlugin
from backend.plugins.dahua import DahuaPlugin
from backend.plugins.generic import GenericStreamPlugin
from backend.plugins.registry import PLUGINS, detect_brand
from backend.plugins.godrej import GodrejPlugin
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.honeywell import HoneywellPlugin
from backend.plugins.matrix import MatrixPlugin
from backend.plugins.tplink import TPLinkPlugin
from backend.plugins.unknown import UnknownPlugin
from backend.plugins.uniview import UniviewPlugin
from backend.correlation import correlate_segments
from backend import face_search
from backend.face_detection import FACE_DETECTION_LABEL, detect_faces_in_video
from backend.face_search import FaceEmbeddingRecord, index_faces_for_search
from backend import accuracy as accuracy_mod
from backend import imaging
from backend import object_detection
from backend.reconstructor import label_all
from backend.reporting import generate_report
from backend.timeline import TimelineData, build_timeline, normalize_to_utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger("main")

# ── Constants ─────────────────────────────────────────────────────────────────

SESSION_COOKIE_NAME = "sih_session"

# Endpoints that do NOT require an authenticated session.
# Everything else under /api/* is protected.
_AUTH_EXEMPT_PATHS = {
    "/api/auth/status",
    "/api/auth/status-with-session",
    "/api/auth/login",
    "/api/auth/setup",
    "/api/docs",
    "/api/openapi.json",
}

# ── Global state ──────────────────────────────────────────────────────────────

def _create_database():
    """
    Postgres (Supabase) when DATABASE_URL is set, SQLite otherwise.
    SQLite remains the zero-config local/offline fallback.
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        from backend.db_postgres import PostgresDatabase
        return PostgresDatabase(database_url)
    return Database()


db = _create_database()
auth: AuthManager = AuthManager(db)

# Per-case: {case_id → asyncio.Queue[ScanProgress]}
_progress_queues: dict[str, asyncio.Queue] = {}
# Per-case: open EvidenceImage (kept alive for export)
_open_images: dict[str, EvidenceImage] = {}
# Per-case: AuditLog
_audit_logs: dict[str, AuditLog] = {}
# Per-case scan tasks (for pause/resume via simple event)
_scan_tasks: dict[str, asyncio.Task] = {}
# Per-case: evidence_id currently being scanned (drives the evidence table's
# "SCANNING" badge in get_case() — cleared when _run_scan() finishes/errors).
_active_scan_evidence: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, auth
    if not hasattr(db, "_path"):
        db = _create_database()
        auth = AuthManager(db)
    log.info("Database initialised at %s", db._path)

    # ── Startup binding check ──────────────────────────────────────────────────
    # The bind address is controlled by uvicorn CLI args (in run.bat/run.sh),
    # not by FastAPI.  We inspect the environment variable used by our start
    # scripts and warn loudly if it looks like it's been changed.
    host_env = os.environ.get("SIH_HOST", "127.0.0.1").strip()
    if host_env not in ("127.0.0.1", "localhost"):
        _BINDING_WARNING = (
            "\n"
            "╔══════════════════════════════════════════════════════════════════════╗\n"
            "║  ⚠  SECURITY WARNING: Non-localhost binding detected               ║\n"
            f"║  SIH_HOST is set to '{host_env}'.                                  \n"
            "║  This tool is designed for LOCAL-ONLY use.                          ║\n"
            "║  Binding to a network interface exposes forensic case data          ║\n"
            "║  and session cookies to the local network.                          ║\n"
            "║  Set SIH_HOST=127.0.0.1 or remove the variable to use defaults.    ║\n"
            "╚══════════════════════════════════════════════════════════════════════╝\n"
        )
        log.warning(_BINDING_WARNING)
        sys.stderr.write(_BINDING_WARNING)

    yield

    # Close any open images on shutdown
    for img in list(_open_images.values()):
        try:
            img.close()
        except Exception:
            pass


# ── Auth middleware ───────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette-level middleware that enforces session authentication on every
    /api/* request (except the explicitly exempted auth endpoints).

    Per-request session enforcement:
      1. Read sih_session cookie.
      2. Call auth.validate_session() — this checks elapsed time and deletes
         expired sessions.  Returns False if missing, invalid, or timed out.
      3. On invalid → return 401 JSON immediately; request never reaches a route.
      4. On valid → touch_session() to refresh last_activity, then proceed.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only protect /api/* routes
        if path.startswith("/api/") and path not in _AUTH_EXEMPT_PATHS:
            token = request.cookies.get(SESSION_COOKIE_NAME)
            # validate_session() is synchronous but fast (dict lookup + time check)
            if not auth.validate_session(token):
                return JSONResponse(
                    {"detail": "Not authenticated. Please log in."},
                    status_code=401,
                )
            # Session is valid — refresh activity timestamp
            auth.touch_session(token)

        response = await call_next(request)
        return response


app = FastAPI(
    title="SIH26150 DVR/NVR Forensic Tool",
    version="1.0.0-dev",
    docs_url="/api/docs",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)

# ── Plugin registry ───────────────────────────────────────────────────────────
# Lives in backend/plugins/registry.py so analysis code can use it without importing the web app.
_PLUGINS = PLUGINS
_detect_brand = detect_brand


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_case_audit_log(case_id: str) -> AuditLog:
    """
    Return the in-memory AuditLog for a case, rehydrating it from the database
    on first access after a restart so history isn't silently lost.
    """
    audit = _audit_logs.get(case_id)
    if audit is None:
        audit = AuditLog.from_entries(db.load_audit_entries(case_id))
        _audit_logs[case_id] = audit
    return audit


def _audit(case_id: str, action: str, details: str = "") -> None:
    audit = _get_case_audit_log(case_id)
    entry = audit.append(action, details)
    try:
        db.save_audit_entry(entry, case_id=case_id)
    except Exception:
        pass


async def _push_progress(case_id: str, prog: ScanProgress) -> None:
    q = _progress_queues.get(case_id)
    if q:
        await q.put(prog)


# ── Global audit log for access events ───────────────────────────────────────
# Login/logout events are recorded in a global (not per-case) audit log so
# they appear in the same hash-chained trail as evidence operations.
# Rehydrated from the database so this history survives a server restart —
# it is cited as evidence-integrity proof, so it must not silently reset.
_global_audit = AuditLog.from_entries(db.load_audit_entries(case_id=None))


def _global_audit_event(action: str, details: str = "") -> None:
    """Append to the global access audit log (login/logout events)."""
    entry = _global_audit.append(action, details)
    try:
        db.save_audit_entry(entry, case_id=None)
    except Exception:
        pass


# ── Background scan ───────────────────────────────────────────────────────────

async def _run_scan(case_id: str, evidence_id: str) -> None:
    """
    Full async scan pipeline. Runs in a background task.
    Progress is pushed to _progress_queues[case_id].
    """
    loop = asyncio.get_event_loop()

    async def push(phase, percent=0, message="", frames=0, done=0, total=0):
        await _push_progress(case_id, ScanProgress(
            phase=phase, percent=percent, message=message,
            frames_found=frames, bytes_done=done, total_bytes=total,
        ))

    try:
        ev = await asyncio.to_thread(db.get_evidence, evidence_id)
        if not ev:
            await push(ScanPhase.ERROR, message=f"Evidence {evidence_id} not found")
            return

        # ── Step 1: open image ─────────────────────────────────────────────
        await push(ScanPhase.HASHING, 0, "Opening image and computing SHA-256 + MD5…")
        _audit(case_id, "scan_start", f"evidence_id={evidence_id}")

        def _progress_cb(done, total):
            pct = 100 * done / total if total else 0
            asyncio.run_coroutine_threadsafe(
                _push_progress(case_id, ScanProgress(
                    phase=ScanPhase.HASHING,
                    percent=pct * 0.3,
                    message="Hashing…",
                    bytes_done=done,
                    total_bytes=total,
                )),
                loop,
            )

        img = await asyncio.to_thread(EvidenceImage.open, Path(ev.path), _progress_cb)
        _open_images[case_id] = img
        ev.sha256_before = img.sha256_before
        ev.md5_before    = img.md5_before
        ev.size_bytes    = img.size
        await asyncio.to_thread(db.save_evidence, ev)
        _audit(case_id, "hashed", f"sha256={img.sha256_before} md5={img.md5_before}")

        # ── Step 2: brand detection ────────────────────────────────────────
        await push(ScanPhase.DETECTING, 32, "Detecting brand…")
        brand, version, confidence, plugin = await asyncio.to_thread(_detect_brand, img)
        ev.brand         = brand
        ev.brand_version = version
        ev.confidence    = confidence
        await asyncio.to_thread(db.save_evidence, ev)
        _audit(case_id, "brand_detected", f"brand={brand} confidence={confidence:.2f} version={version}")

        generic_fallback = False
        unidentified_msg = (
            f"Brand confidence {confidence:.0%} is below threshold "
            f"({MIN_PLUGIN_CONFIDENCE:.0%}) and generic stream carving found no "
            f"recoverable MPEG-PS / H.264 video. Disk may be unsupported, encrypted, "
            f"or not a DVR/NVR disk. Details: {plugin.version_hint()}"
        )
        if confidence < MIN_PLUGIN_CONFIDENCE:
            # No brand plugin recognised the disk. Rather than give up, try generic
            # standards-based stream carving (recorders with undocumented formats may
            # still store standard MPEG-PS / H.264 streams). No brand is claimed.
            generic_fallback = True
            hinted = plugin if (confidence > 0 and not isinstance(plugin, UnknownPlugin)) else None
            plugin = GenericStreamPlugin()
            ev.brand         = (f"{hinted.display_name} — generic stream carving" if hinted
                                else plugin.display_name)
            ev.brand_version = plugin.version_hint()
            await asyncio.to_thread(db.save_evidence, ev)
            _audit(case_id, "brand_unidentified",
                   f"best_confidence={confidence:.2f}; falling back to generic stream carving")
            await push(ScanPhase.DETECTING, 35,
                       f"Brand not recognised (best confidence {confidence:.0%}) — "
                       f"trying generic standards-based stream carving…")
        else:
            await push(ScanPhase.DETECTING, 35,
                       f"Detected: {plugin.display_name} (confidence {confidence:.0%})")

        # ── Step 3: index read ─────────────────────────────────────────────
        await push(ScanPhase.INDEX_READ, 36, "Reading index (if available)…")
        index_frames, index_note = await asyncio.to_thread(plugin.list_recordings, img)
        _audit(case_id, "index_read", index_note)
        await push(ScanPhase.INDEX_READ, 40,
                   f"Index: {len(index_frames)} frames. {index_note}")

        # ── Step 4: carving ────────────────────────────────────────────────
        await push(ScanPhase.CARVING, 40, "Carving for deleted/lost video…")

        frames_ref = {"count": 0}

        def _carve_progress(done, total):
            pct = 40 + 40 * done / total if total else 40
            frames_ref["count"] += 0
            asyncio.run_coroutine_threadsafe(
                _push_progress(case_id, ScanProgress(
                    phase=ScanPhase.CARVING,
                    percent=pct,
                    message="Carving…",
                    bytes_done=done,
                    total_bytes=total,
                    frames_found=frames_ref["count"],
                )),
                loop,
            )

        carved_frames, carve_note = await asyncio.to_thread(plugin.carve, img, _carve_progress)
        _audit(case_id, "carving_done", carve_note)

        if generic_fallback and not carved_frames:
            await push(ScanPhase.ERROR, message=unidentified_msg)
            return

        all_frames = index_frames + carved_frames
        await push(ScanPhase.CARVING, 80,
                   f"Carving done: {len(carved_frames)} frames. {carve_note}")

        # ── Step 5: reconstruct ────────────────────────────────────────────
        await push(ScanPhase.RECONSTRUCTING, 82, "Grouping by camera and sorting by time…")
        segments = await asyncio.to_thread(label_all, all_frames, evidence_id)
        # Clear any segments (and cached face embeddings) from a previous scan
        # of this evidence before saving the fresh set — otherwise re-running
        # a scan accumulates duplicate, contradictory segment rows instead of
        # replacing them.
        await asyncio.to_thread(db.delete_segments_for_evidence, evidence_id)
        for seg in segments:
            await asyncio.to_thread(db.save_segment, seg)
        _audit(case_id, "reconstruction_done",
               f"{len(segments)} segments across {len({s.camera for s in segments})} cameras")

        # ── Step 6: re-verify ──────────────────────────────────────────────
        await push(ScanPhase.RECONSTRUCTING, 95, "Re-verifying evidence hash…")
        unchanged = await asyncio.to_thread(img.verify_unchanged)
        ev.sha256_after = img.sha256_before if unchanged else "MISMATCH"
        await asyncio.to_thread(db.save_evidence, ev)
        _audit(case_id, "verify", f"unchanged={unchanged} sha256_after={ev.sha256_after}")

        await push(ScanPhase.DONE, 100,
                   f"Done. {len(segments)} segments found. "
                   f"Hash {'✓ matches' if unchanged else '✗ MISMATCH'}.")

    except AcquisitionError as exc:
        _audit(case_id, "acquisition_error", str(exc))
        await push(ScanPhase.ERROR, message=f"Acquisition error: {exc}")
    except Exception as exc:
        tb = traceback.format_exc()
        log.error("Scan error in case %s: %s\n%s", case_id, exc, tb)
        _audit(case_id, "scan_error", str(exc))
        await push(ScanPhase.ERROR, message=f"Unexpected error: {exc}")
    finally:
        _active_scan_evidence.pop(case_id, None)
        q = _progress_queues.get(case_id)
        if q:
            await q.put(None)  # sentinel


# ── Auth API routes ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long.")
        return v


@app.get("/api/auth/status")
async def auth_status():
    """
    Unauthenticated endpoint — lets the frontend decide on first load whether
    to show the setup screen, login screen, or dashboard.
    Returns: {password_set: bool, authenticated: bool}
    """
    # We can't read the cookie in a plain route without Request; use Request param
    # to match middleware expectation.  This route is exempt from middleware auth.
    return {
        "password_set": auth.is_password_set(),
        "authenticated": False,  # client-side always checks cookie via middleware
    }


@app.get("/api/auth/status-with-session")
async def auth_status_with_session(request: Request):
    """
    Same as /api/auth/status but also reports whether the current session cookie
    is valid.  Used by the frontend to handle mid-session expiry redirects.
    Exempt from middleware (checked manually here).
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return {
        "password_set": auth.is_password_set(),
        "authenticated": auth.validate_session(token),
    }


@app.post("/api/auth/setup")
async def setup_password(req: SetupRequest, response: Response):
    """
    First-run endpoint: set the examiner password.
    Only works when no password has been set yet.
    After setting the password, a session is created automatically.
    """
    was_set = await asyncio.to_thread(auth.set_password_if_unset, req.password)
    if not was_set:
        raise HTTPException(400, "Password is already set. Use the login endpoint.")

    # Auto-login after setup
    token = auth.create_session()
    auth.record_success()

    # Audit: no password details logged
    _global_audit_event("examiner_password_set", "First-run password created")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,          # JS cannot read — blocks XSS token theft
        samesite="strict",      # Blocks basic CSRF
        # secure=True would be added if this were ever served over HTTPS.
        # On localhost HTTP, secure=True would prevent the cookie from being sent.
        max_age=None,           # Session cookie — expires when browser closes
    )
    return {"ok": True}


@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    """
    Login endpoint. Protected against brute force by per-account lockout.

    Security properties:
      • Error message is always "Incorrect password." — never reveals whether
        an account exists or why the check failed.
      • Attempted password is NEVER logged, not even on failure.
      • Audit entry records only: timestamp (via AuditLog) + attempt count.
    """
    # Check lockout BEFORE verifying password
    locked, retry_after = auth.is_locked_out()
    if locked:
        return JSONResponse(
            {"locked": True, "retry_after": retry_after,
             "detail": f"Too many failed attempts. Try again in {retry_after} seconds."},
            status_code=429,
        )

    # Verify password (constant-time bcrypt comparison)
    ok = await asyncio.to_thread(auth.verify_password, req.password)

    if not ok:
        failure_count, just_locked = auth.record_failure()
        # Audit: timestamp and count only — NO password content
        _global_audit_event(
            "login_failure",
            f"attempt={failure_count} locked={just_locked}",
        )
        if just_locked:
            return JSONResponse(
                {"locked": True, "retry_after": AuthManager.LOCKOUT_SECONDS,
                 "detail": f"Too many failed attempts. Try again in {AuthManager.LOCKOUT_SECONDS} seconds."},
                status_code=429,
            )
        return JSONResponse(
            {"ok": False, "detail": "Incorrect password."},
            status_code=401,
        )

    # Success
    token = auth.create_session()
    auth.record_success()

    # Audit: success, no credentials
    _global_audit_event("login_success", "Examiner authenticated")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,          # JS cannot read — blocks XSS token theft
        samesite="strict",      # Blocks basic CSRF
        # secure=True would be set if this were served over HTTPS.
        # On localhost HTTP, secure=True prevents the cookie from being sent.
        max_age=None,           # Session cookie
    )
    return {"ok": True}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """
    Invalidate the current session. No credentials required — the session
    cookie itself is the proof of identity.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth.invalidate_session(token)
    _global_audit_event("logout", "Session invalidated")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/global-audit")
async def global_audit_log():
    """Return the global access audit log (login/logout events)."""
    chain_ok, error = _global_audit.verify_chain()
    return {
        "chain_intact": chain_ok,
        "error": error,
        "entries": _global_audit.export_entries(),
    }


# ── API routes ────────────────────────────────────────────────────────────────

# Allowed characters for case numbers: alphanumeric, dash, slash, underscore
_CASE_NUMBER_RE = re.compile(r'^[\w\-/]{1,64}$')
# Allowed file extensions for evidence disk images
_ALLOWED_EVIDENCE_EXTS = {".dd", ".img", ".raw", ".bin"}


class CreateCaseRequest(BaseModel):
    case_number: str
    examiner:    str
    notes:       Optional[str] = None

    @field_validator("case_number")
    @classmethod
    def _validate_case_number(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Case number is required.")
        if not _CASE_NUMBER_RE.match(v):
            raise ValueError(
                "Case number must be 1–64 characters and may only contain "
                "letters, digits, dashes (-), slashes (/), and underscores (_)."
            )
        return v

    @field_validator("examiner")
    @classmethod
    def _validate_examiner(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Examiner name must be at least 2 characters.")
        if len(v) > 128:
            raise ValueError("Examiner name must be 128 characters or fewer.")
        # Strip ASCII control characters
        v = "".join(ch for ch in v if ch >= " ")
        return v


class LoadEvidenceRequest(BaseModel):
    path: str  # absolute path to .dd / .img file on the examiner's machine
    # Examiner-confirmed device clock offset from UTC, in minutes (e.g. +330
    # for IST). Optional and never inferred automatically — see
    # Evidence.device_utc_offset_minutes and timeline.normalize_to_utc.
    device_utc_offset_minutes: Optional[int] = None

    @field_validator("device_utc_offset_minutes")
    @classmethod
    def _validate_offset(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (-720 <= v <= 840):
            raise ValueError(
                "device_utc_offset_minutes must be between -720 (UTC-12:00) "
                "and 840 (UTC+14:00)."
            )
        return v

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Evidence file path is required.")
        # Reject path traversal attempts
        if ".." in v:
            raise ValueError(
                "Path must not contain '..' directory traversal sequences."
            )
        # Reject physical drive paths (Windows \\.\PhysicalDriveN style)
        if v.startswith("\\\\.\\") or v.lower().startswith("//./"):
            raise ValueError(
                "Physical drive paths (e.g. \\\\.\\PhysicalDrive0) are rejected "
                "to prevent accidental modification of live drives. "
                "Acquire a raw disk image (.dd/.img) first."
            )
        # Check extension
        ext = Path(v).suffix.lower()
        if ext not in _ALLOWED_EVIDENCE_EXTS:
            raise ValueError(
                f"Evidence file must be a raw disk image with one of these extensions: "
                f"{', '.join(sorted(_ALLOWED_EVIDENCE_EXTS))}. Got: '{ext or '(none)'}'"
            )
        return v


@app.post("/api/cases", response_model=Case)
async def create_case(req: CreateCaseRequest):
    case = Case(case_number=req.case_number, examiner=req.examiner, notes=req.notes)
    try:
        result = await asyncio.to_thread(db.create_case, case)
    except DuplicateCaseNumberError:
        raise HTTPException(
            409,
            f"Case number '{req.case_number}' already exists. "
            "Each case must have a unique case number."
        )
    _audit(case.case_id, "case_created", f"case_number={req.case_number} examiner={req.examiner}")
    return result


@app.get("/api/cases")
async def list_cases():
    return await asyncio.to_thread(db.list_cases)


@app.get("/api/cases/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str):
    """Return the case together with its evidence, segments, log events and audit entries.

    All child arrays are always present (empty list when nothing exists) so the
    frontend never receives ``undefined`` when calling ``.length`` or iterating.
    """
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, f"Case '{case_id}' not found")

    evidence = await asyncio.to_thread(db.list_evidence_for_case, case_id)

    # Collect segments for all evidence items belonging to this case, and
    # derive each evidence item's scan_status while we're already looking up
    # its segments (COMPLETED once segments exist, SCANNING while the active
    # scan task targets it, PENDING otherwise — see _active_scan_evidence).
    segments: list = []
    log_events: list = []
    active_evidence_id = _active_scan_evidence.get(case_id)
    enriched_evidence: list = []
    for ev in evidence:
        segs = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
        segments.extend(segs)
        les = await asyncio.to_thread(db.list_log_events, ev.evidence_id)
        log_events.extend(les)

        if segs:
            status = "COMPLETED"
        elif ev.evidence_id == active_evidence_id:
            status = "SCANNING"
        else:
            status = "PENDING"
        enriched_evidence.append(ev.model_copy(update={"scan_status": status}))
    evidence = enriched_evidence

    # Audit entries from in-memory log (re-hydrate from DB if server was restarted)
    audit_log = _get_case_audit_log(case_id)
    audit_entries = [AuditEntry(**e) for e in audit_log.export_entries()]

    return CaseDetail(
        **case.model_dump(),
        evidence=evidence,
        segments=segments,
        log_events=log_events,
        audit=audit_entries,
    )


@app.post("/api/cases/{case_id}/evidence")
async def load_evidence(case_id: str, req: LoadEvidenceRequest, bg: BackgroundTasks):
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    path = Path(req.path)
    if not path.is_file():
        raise HTTPException(400, f"File not found or not a regular file: {req.path}")

    ev = Evidence(
        case_id=case_id,
        path=str(path),
        device_utc_offset_minutes=req.device_utc_offset_minutes,
    )
    ev = await asyncio.to_thread(db.save_evidence, ev)
    _audit(case_id, "evidence_loaded", f"path={req.path}")

    # Ensure progress queue exists (the audit log is ensured by _audit() above)
    _progress_queues[case_id] = asyncio.Queue()

    return ev


@app.post("/api/cases/{case_id}/evidence/upload")
async def upload_evidence(
    case_id: str,
    file: UploadFile = File(...),
    device_utc_offset_minutes: Optional[int] = Form(None),
):
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    if device_utc_offset_minutes is not None and not (-720 <= device_utc_offset_minutes <= 840):
        raise HTTPException(400, "device_utc_offset_minutes must be between -720 and 840.")

    # Sanitize file name to avoid directory traversal
    filename = Path(file.filename or "evidence.raw").name
    safe_filename = re.sub(r"[^a-zA-Z0-9_.\- ]", "_", filename).strip()
    if not safe_filename:
        safe_filename = "evidence.raw"

    evidence_dir = get_case_evidence_dir(case_id)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    target_path = evidence_dir / safe_filename
    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_path = evidence_dir / f"{stem}_{timestamp_str}{suffix}"

    async with aiofiles.open(target_path, "wb") as out_file:
        while chunk := await file.read(1024 * 1024):
            await out_file.write(chunk)

    ev = Evidence(
        case_id=case_id,
        path=str(target_path),
        device_utc_offset_minutes=device_utc_offset_minutes,
    )
    ev = await asyncio.to_thread(db.save_evidence, ev)
    _audit(case_id, "evidence_uploaded", f"filename={safe_filename} path={target_path}")

    _progress_queues[case_id] = asyncio.Queue()

    return ev


@app.post("/api/cases/{case_id}/scan")
async def start_scan(case_id: str, bg: BackgroundTasks):
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence loaded for this case")
    ev = evs[-1]  # scan the most recently loaded evidence

    if case_id not in _progress_queues:
        _progress_queues[case_id] = asyncio.Queue()

    task = asyncio.create_task(_run_scan(case_id, ev.evidence_id))
    _scan_tasks[case_id] = task
    _active_scan_evidence[case_id] = ev.evidence_id
    _audit(case_id, "scan_started", f"evidence_id={ev.evidence_id}")
    return {"status": "started", "evidence_id": ev.evidence_id}


@app.get("/api/cases/{case_id}/status")
async def scan_status_sse(case_id: str):
    """Server-Sent Events stream of ScanProgress updates."""
    q = _progress_queues.get(case_id)
    if not q:
        raise HTTPException(404, "No active scan for this case")

    async def _gen() -> AsyncGenerator[str, None]:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                yield "data: {\"type\":\"ping\"}\n\n"
                continue
            if msg is None:  # sentinel
                yield "data: {\"type\":\"done\"}\n\n"
                break
            yield f"data: {msg.model_dump_json()}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/api/cases/{case_id}/segments")
async def list_segments(case_id: str, evidence_id: Optional[str] = None):
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        return []
    if evidence_id:
        ev = next((e for e in evs if e.evidence_id == evidence_id), None)
        if not ev:
            raise HTTPException(404, f"Evidence '{evidence_id}' not found in case '{case_id}'")
    else:
        ev = evs[-1]  # most recently loaded evidence
    return await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)


@app.get("/api/cases/{case_id}/timeline", response_model=TimelineData)
async def case_timeline(case_id: str):
    """Return all recoverable case segments arranged for a shared timeline view."""
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    evidence = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    segments: list[Segment] = []
    for item in evidence:
        segments.extend(await asyncio.to_thread(db.list_segments_for_evidence, item.evidence_id))
    return await asyncio.to_thread(build_timeline, segments)


@app.get("/api/cases/{case_id}/correlation")
async def case_correlation(case_id: str, window_seconds: float = 5.0):
    """
    Cross-camera event correlation: groups recovered segments whose time
    windows overlap (within `window_seconds`) across 2+ distinct camera
    channels. Time-window clustering only — no face/object/content analysis.

    When an evidence item has a confirmed device_utc_offset_minutes, its
    segments' timestamps are normalized to UTC before correlating, so
    evidence from devices in different timezones lines up correctly. Segments
    from evidence with no confirmed offset are correlated using their raw
    device-reported timestamps as-is.
    """
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    evidence = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    segments: list[Segment] = []
    for item in evidence:
        evidence_segments = await asyncio.to_thread(db.list_segments_for_evidence, item.evidence_id)
        offset = item.device_utc_offset_minutes
        for seg in evidence_segments:
            if offset is not None:
                seg = seg.model_copy(update={
                    "start_time": normalize_to_utc(seg.start_time, offset),
                    "end_time": normalize_to_utc(seg.end_time, offset),
                })
            segments.append(seg)

    events = await asyncio.to_thread(correlate_segments, segments, window_seconds)
    return {
        "events": [e.to_dict() for e in events],
        "any_evidence_normalized": any(e.device_utc_offset_minutes is not None for e in evidence),
    }


@app.post("/api/cases/{case_id}/export/{segment_id}")
async def export_one_segment(case_id: str, segment_id: str):
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    segments = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
    seg = next((s for s in segments if s.segment_id == segment_id), None)
    if not seg:
        raise HTTPException(404, "Segment not found")

    img = _open_images.get(case_id)
    if not img or img.mm is None:
        raise HTTPException(400, "Evidence image is not loaded; re-run scan first")

    out_dir = get_case_export_dir(case_id)
    seg, detail = await asyncio.to_thread(export_segment, img.mm, seg, out_dir)
    await asyncio.to_thread(db.save_segment, seg)
    _audit(case_id, "export", json.dumps(detail))
    return {"segment": seg, "detail": detail}


@app.post("/api/cases/{case_id}/motion/{segment_id}")
async def detect_segment_motion(case_id: str, segment_id: str):
    """
    Optional post-export Basic Motion Detection.
    Decoupled from carving/recovery — operates read-only on exported video files.
    """
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    segments = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
    seg = next((s for s in segments if s.segment_id == segment_id), None)
    if not seg:
        raise HTTPException(404, "Segment not found")

    if not seg.export_path or not Path(seg.export_path).is_file():
        raise HTTPException(400, "Segment has not been exported yet. Export to MP4 before running motion detection.")

    res = await asyncio.to_thread(detect_motion_in_video, seg.export_path)
    if res.error:
        raise HTTPException(500, f"Basic Motion Detection error: {res.error}")

    seg.motion_detected = res.motion_detected
    seg.motion_details = res.summary
    await asyncio.to_thread(db.save_segment, seg)

    _audit(
        case_id,
        "basic_motion_detection",
        f"segment_id={segment_id} motion_detected={res.motion_detected} frames={res.motion_frames}/{res.total_frames}",
    )
    return {
        "segment_id": seg.segment_id,
        "motion_detected": res.motion_detected,
        "details": res.summary,
        "motion_frames": res.motion_frames,
        "total_frames": res.total_frames,
        "motion_ratio": res.motion_ratio,
        "label": "Basic Motion Detection",
    }


@app.post("/api/cases/{case_id}/face-detect/{segment_id}")
async def detect_segment_faces(case_id: str, segment_id: str):
    """
    Optional post-export AI-Based Face Detection (OpenCV YuNet CNN).
    Decoupled from carving/recovery — operates read-only on exported video files.
    Detection only: no face recognition/identification is performed or claimed.
    """
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    segments = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
    seg = next((s for s in segments if s.segment_id == segment_id), None)
    if not seg:
        raise HTTPException(404, "Segment not found")

    if not seg.export_path or not Path(seg.export_path).is_file():
        raise HTTPException(400, "Segment has not been exported yet. Export to MP4 before running face detection.")

    res = await asyncio.to_thread(detect_faces_in_video, seg.export_path)
    if res.error:
        raise HTTPException(500, f"Face detection error: {res.error}")

    seg.face_detected = res.faces_detected
    seg.face_detection_details = res.summary
    await asyncio.to_thread(db.save_segment, seg)

    # Side effect: index face embeddings so this segment becomes searchable
    # via /face-search without re-decoding the video on every search.
    indexed_count = 0
    if res.faces_detected:
        records = await asyncio.to_thread(index_faces_for_search, seg.export_path)
        await asyncio.to_thread(db.save_face_embeddings, segment_id, records)
        indexed_count = len(records)

    _audit(
        case_id,
        "face_detection",
        f"segment_id={segment_id} faces_detected={res.faces_detected} "
        f"frames_with_faces={res.frames_with_faces}/{res.frames_sampled}",
    )
    return {
        "segment_id": seg.segment_id,
        "faces_detected": res.faces_detected,
        "details": res.summary,
        "frames_with_faces": res.frames_with_faces,
        "frames_sampled": res.frames_sampled,
        "total_frames": res.total_frames,
        "max_faces_in_single_frame": res.max_faces_in_single_frame,
        "label": FACE_DETECTION_LABEL,
        "faces_indexed_for_search": indexed_count,
    }


@app.post("/api/cases/{case_id}/face-search")
async def search_faces(case_id: str, reference_image: UploadFile = File(...)):
    """
    Search for faces similar to an uploaded reference photo across every
    segment in this case that has already been indexed (see
    detect_segment_faces, which indexes as a side effect).

    IMPORTANT: results are ranked by similarity, NOT confirmed identities.
    See backend/face_search.py's module docstring for a real false-match
    example observed during this project's own verification testing.
    """
    if not face_search.models_available():
        raise HTTPException(500, "Face search models are not installed on this server.")

    image_bytes = await reference_image.read()
    reference_embedding = await asyncio.to_thread(
        face_search.extract_embedding_from_image_bytes, image_bytes
    )
    if reference_embedding is None:
        raise HTTPException(400, "No face was detected in the uploaded reference photo.")

    evidence = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    segment_ids: list[str] = []
    for ev_item in evidence:
        segs = await asyncio.to_thread(db.list_segments_for_evidence, ev_item.evidence_id)
        segment_ids.extend(s.segment_id for s in segs)

    raw_records = await asyncio.to_thread(db.list_face_embeddings_for_segments, segment_ids)
    candidates = [
        (r["segment_id"], FaceEmbeddingRecord(
            frame_offset_seconds=r["frame_offset_seconds"],
            bbox=r["bbox"],
            embedding=r["embedding"],
        ))
        for r in raw_records
    ]

    matches = await asyncio.to_thread(face_search.rank_matches, reference_embedding, candidates)

    _audit(case_id, "face_search", f"candidates_searched={len(candidates)} matches_returned={len(matches)}")

    return {
        "label": face_search.FACE_SEARCH_LABEL,
        "reference_threshold": face_search.REFERENCE_MATCH_THRESHOLD,
        "warning": (
            "Similarity scores are candidates for human review, NOT confirmed identity "
            "matches. Different people can score above the reference threshold shown "
            "here — always corroborate with independent evidence before relying on a match."
        ),
        "segments_indexed": len(set(segment_ids) & {c[0] for c in candidates}),
        "matches": [m.to_dict() for m in matches],
    }


@app.get("/api/cases/{case_id}/verify")
async def verify_evidence(case_id: str):
    # Re-open the evidence file by its stored path rather than relying on an
    # in-memory handle from a previous scan (which is lost on server restart).
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    if not ev.sha256_before:
        raise HTTPException(400, "Evidence has not been hashed yet — run a scan first")
    if not Path(ev.path).is_file():
        raise HTTPException(404, f"Evidence file not found at {ev.path}")
    try:
        unchanged, current = await asyncio.to_thread(verify_disk_image_integrity, ev.path, ev.sha256_before)
    except AcquisitionError as exc:
        raise HTTPException(400, f"Could not open evidence for verification: {exc}")
    _audit(case_id, "verify_requested", f"unchanged={unchanged} sha256_now={current}")
    return {"unchanged": unchanged, "sha256": ev.sha256_before, "current_sha256": current}


# ── Accuracy against ground truth ─────────────────────────────────────────────

def _load_accuracy_results(case_id: str) -> list[dict]:
    d = get_case_accuracy_dir(case_id)
    out: list[dict] = []
    if d.is_dir():
        for f in d.glob("result_*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


def _parse_truth_log(raw: bytes) -> list[dict]:
    """Accepts {"recordings": [...]} or a bare list of {name, camera?, start, end}."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise HTTPException(400, f"Recording log is not valid JSON: {exc}")
    entries = data.get("recordings") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise HTTPException(400, "Recording log must be a non-empty list (or {\"recordings\": [...]}).")
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or "start" not in e or "end" not in e:
            raise HTTPException(400, f"Log entry {i + 1} needs \"start\" and \"end\" (ISO times).")
        try:
            a, b = accuracy_mod._parse_dt(str(e["start"])), accuracy_mod._parse_dt(str(e["end"]))
        except ValueError:
            raise HTTPException(400, f"Log entry {i + 1} has an unreadable start/end time.")
        if b < a:
            raise HTTPException(400, f"Log entry {i + 1} ends before it starts.")
        if "camera" in e and e["camera"] is not None and not isinstance(e["camera"], int):
            raise HTTPException(400, f"Log entry {i + 1}: camera must be an integer.")
    return entries


@app.post("/api/cases/{case_id}/accuracy")
async def run_accuracy(
    case_id: str,
    segment_id: str = Form(...),
    mode: str = Form("exact"),
    log_clock: str = Form("device"),
    original_image_path: Optional[str] = Form(None),
    ground_truth: Optional[UploadFile] = File(None),
    truth_log: Optional[UploadFile] = File(None),
):
    """
    Measure a recovered segment against ground truth the examiner supplies: a known-good video
    (e.g. exported by the vendor player), a recording log, and/or the ORIGINAL pre-deletion disk image.
    Anything not supplied is reported as "not measured" — the tool never invents a percentage.
    """
    if mode not in ("exact", "perceptual"):
        raise HTTPException(400, "mode must be 'exact' or 'perceptual'")
    if log_clock not in ("device", "utc"):
        raise HTTPException(400, "log_clock must be 'device' or 'utc'")
    has_video = ground_truth is not None and bool(ground_truth.filename)
    has_log = truth_log is not None and bool(truth_log.filename)
    has_orig = bool(original_image_path and original_image_path.strip())
    if not (has_video or has_log or has_orig):
        raise HTTPException(400, "Supply at least one ground truth: a video, a recording log, or the original disk image.")

    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    segments = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
    seg = next((s for s in segments if s.segment_id == segment_id), None)
    if seg is None:
        raise HTTPException(404, "Segment not found")

    log_entries = None
    if has_log:
        log_entries = _parse_truth_log(await truth_log.read())
    if has_orig:
        if not Path(original_image_path.strip()).is_file():
            raise HTTPException(400, f"Original image not found or not a regular file: {original_image_path}")

    acc_dir = get_case_accuracy_dir(case_id)
    acc_dir.mkdir(parents=True, exist_ok=True)
    result_id = str(uuid4())
    truth_path: Optional[Path] = None
    if has_video:
        name = re.sub(r"[^a-zA-Z0-9_.\- ]", "_", Path(ground_truth.filename).name).strip() or "truth.bin"
        truth_path = acc_dir / f"truth_{result_id}_{name}"
        async with aiofiles.open(truth_path, "wb") as out:
            while chunk := await ground_truth.read(1024 * 1024):
                await out.write(chunk)

    inputs = accuracy_mod.AccuracyInputs(
        segment=seg, all_segments=segments, truth_file=truth_path, log_entries=log_entries,
        log_clock=log_clock, original_image=original_image_path.strip() if has_orig else None,
        mode=mode, device_utc_offset_minutes=ev.device_utc_offset_minutes,
    )
    result = await asyncio.to_thread(accuracy_mod.run_accuracy_check, inputs)
    result["result_id"] = result_id
    result["case_id"] = case_id
    result["truth_file"] = truth_path.name if truth_path else None
    result["original_image_path"] = inputs.original_image
    result["segment_status"] = seg.status.value
    result["segment_sha256"] = seg.sha256
    result["measured_meaning"] = (
        "Figures below exist only because ground truth was supplied for this test. They describe this one segment, "
        "this one recorder disk and this one deletion; they do not describe recovery in general."
    )
    (acc_dir / f"result_{result_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    _audit(case_id, "accuracy_check",
           f"segment={segment_id} truth_sha256={(result.get('bytes') or {}).get('truth_sha256', '-')} "
           f"| {accuracy_mod.summarize(result)}")
    return result


@app.get("/api/cases/{case_id}/accuracy")
async def list_accuracy(case_id: str):
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return await asyncio.to_thread(_load_accuracy_results, case_id)


# ── Object detection ──────────────────────────────────────────────────────────

def _load_object_results(case_id: str) -> list[dict]:
    d = get_case_analysis_dir(case_id)
    out: list[dict] = []
    if d.is_dir():
        for f in d.glob("objects_*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


@app.post("/api/cases/{case_id}/object-detect/{segment_id}")
async def detect_segment_objects(case_id: str, segment_id: str):
    """
    Optional post-export object detection (YOLOX when a model file is present, otherwise the
    classical HOG person detector). Read-only on the exported video; result stored with the case.
    """
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    segments = await asyncio.to_thread(db.list_segments_for_evidence, evs[-1].evidence_id)
    seg = next((s for s in segments if s.segment_id == segment_id), None)
    if not seg:
        raise HTTPException(404, "Segment not found")
    if not seg.export_path or not Path(seg.export_path).is_file():
        raise HTTPException(400, "Segment has not been exported yet. Export to MP4 before running object detection.")

    res = await asyncio.to_thread(object_detection.detect_objects_in_video, seg.export_path)
    if res.error:
        raise HTTPException(500, f"Object detection error: {res.error}")

    data = res.to_dict()
    data.update({
        "segment_id": segment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "export_sha256": seg.sha256,
    })
    d = get_case_analysis_dir(case_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"objects_{segment_id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    _audit(case_id, "object_detection",
           f"segment_id={segment_id} engine={res.engine} classes={sorted(res.classes)} "
           f"frames_sampled={res.frames_sampled}")
    return data


@app.get("/api/cases/{case_id}/object-detect")
async def list_object_results(case_id: str):
    return {"results": await asyncio.to_thread(_load_object_results, case_id),
            "engine_available": {"yolox": object_detection.model_available(), "hog": True}}


# ── Acquisition (imaging a local drive / file into a case) ───────────────────

_acquisition_jobs: dict[str, dict] = {}
_background_tasks: set = set()      # keep references so running tasks are not garbage-collected


def _local_acquisition_enabled() -> bool:
    return os.environ.get("FORENSIC_ALLOW_LOCAL_ACQUISITION", "").strip() == "1"


class AcquireRequest(BaseModel):
    source_path: str
    write_blocker_confirmed: bool = False
    verify_source: bool = False
    max_bytes: Optional[int] = None
    device_utc_offset_minutes: Optional[int] = None


@app.get("/api/acquisition/drives")
async def acquisition_drives():
    enabled = _local_acquisition_enabled()
    return {
        "enabled": enabled,
        "drives": await asyncio.to_thread(imaging.list_local_drives) if enabled else [],
        "message": None if enabled else (
            "Drive imaging reads drives attached to the machine running this server, so it is off by default. "
            "Set FORENSIC_ALLOW_LOCAL_ACQUISITION=1 when running the tool locally on the examiner's workstation."
        ),
    }


@app.post("/api/cases/{case_id}/acquire")
async def start_acquisition(case_id: str, req: AcquireRequest):
    if not _local_acquisition_enabled():
        raise HTTPException(403, "Drive imaging is disabled on this server (set FORENSIC_ALLOW_LOCAL_ACQUISITION=1 "
                                 "when running locally on the examiner's workstation).")
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if not req.write_blocker_confirmed:
        raise HTTPException(400, "Confirm that the source is connected through a hardware write blocker.")
    if req.max_bytes is not None and req.max_bytes <= 0:
        raise HTTPException(400, "max_bytes must be positive.")
    if req.device_utc_offset_minutes is not None and not (-720 <= req.device_utc_offset_minutes <= 840):
        raise HTTPException(400, "device_utc_offset_minutes must be between -720 and 840.")
    if _acquisition_jobs.get(case_id, {}).get("state") == "running":
        raise HTTPException(409, "An acquisition is already running for this case.")

    evidence_dir = get_case_evidence_dir(case_id)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = evidence_dir / f"acquired_{stamp}.dd"
    job = {"state": "running", "bytes_done": 0, "total_bytes": None, "dest": str(dest), "error": None, "report": None}
    _acquisition_jobs[case_id] = job
    _audit(case_id, "acquisition_started",
           f"source={req.source_path} dest={dest} write_blocker_attested=True max_bytes={req.max_bytes}")

    def _progress(done: int, total: Optional[int]) -> None:
        job["bytes_done"], job["total_bytes"] = done, total

    async def _run() -> None:
        try:
            report = await asyncio.to_thread(
                imaging.acquire_image, req.source_path, dest,
                write_blocker_attested=True, max_bytes=req.max_bytes,
                verify_source=req.verify_source, progress_cb=_progress,
            )
            ev = Evidence(case_id=case_id, path=str(dest), device_utc_offset_minutes=req.device_utc_offset_minutes,
                          size_bytes=report.bytes_written, sha256_before=report.sha256, md5_before=report.md5)
            ev = await asyncio.to_thread(db.save_evidence, ev)
            _progress_queues[case_id] = asyncio.Queue()
            job.update(state="done", report=report.to_dict(), evidence_id=ev.evidence_id)
            _audit(case_id, "acquisition_completed",
                   f"evidence_id={ev.evidence_id} bytes={report.bytes_written} sha256={report.sha256} "
                   f"md5={report.md5} verified={report.dest_hash_verified} bit_exact={report.is_bit_exact} "
                   f"bad_bytes={report.bad_bytes} source_rehash={report.source_rehash_verified}")
        except (AcquisitionError, OSError) as exc:
            job.update(state="failed", error=str(exc))
            _audit(case_id, "acquisition_failed", str(exc)[:500])
        except Exception as exc:                                   # never leave the job "running"
            log.exception("acquisition crashed")
            job.update(state="failed", error=f"Unexpected error: {exc}")
            _audit(case_id, "acquisition_failed", f"unexpected: {exc}"[:500])

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"state": "running", "dest": str(dest)}


@app.get("/api/cases/{case_id}/acquire/status")
async def acquisition_status(case_id: str):
    job = _acquisition_jobs.get(case_id)
    if not job:
        return {"state": "idle"}
    return job


@app.get("/api/cases/{case_id}/report")
async def get_report(case_id: str):
    case = await asyncio.to_thread(db.get_case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        raise HTTPException(400, "No evidence for this case")
    ev = evs[-1]
    segments  = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
    log_evts  = await asyncio.to_thread(db.list_log_events, ev.evidence_id)
    audit_log = _get_case_audit_log(case_id)
    chain_ok, _ = audit_log.verify_chain()
    entries   = audit_log.export_entries()
    from backend.models import AuditEntry
    audit_entries = [AuditEntry(**e) for e in entries]

    correlated_events = await asyncio.to_thread(correlate_segments, segments)

    report_dir = get_case_report_dir(case_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pdf = report_dir / f"report_{ts}.pdf"

    await asyncio.to_thread(
        generate_report, pdf, case, ev, segments, log_evts, audit_entries, chain_ok,
        correlated_events, _load_accuracy_results(case_id), _load_object_results(case_id),
    )
    _audit(case_id, "report_generated", str(pdf))
    return FileResponse(str(pdf), media_type="application/pdf",
                        filename=f"report_case_{case.case_number}_{ts}.pdf")


@app.get("/api/cases/{case_id}/audit")
async def get_audit(case_id: str):
    audit_log = _get_case_audit_log(case_id)
    chain_ok, error = audit_log.verify_chain()
    return {"chain_intact": chain_ok, "error": error, "entries": audit_log.export_entries()}


# ── Serve frontend static files ───────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

    # no-cache (not no-store): browsers still keep a local copy but MUST
    # revalidate with the server on every load via If-None-Match, rather than
    # trusting a heuristic freshness window. Without this, a browser can serve
    # a stale cached JS/CSS file indefinitely after this tool is updated,
    # silently running old (possibly already-fixed-elsewhere) code — FileResponse
    # already sets ETag/Last-Modified, so revalidation is a cheap 304 when unchanged.
    _NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}

    @app.get("/")
    async def serve_index():
        return FileResponse(str(_FRONTEND_DIR / "index.html"), headers=_NO_CACHE_HEADERS)

    @app.get("/{path:path}")
    async def serve_static(path: str):
        # Resolve against the frontend root and verify the result is still
        # inside it before serving — prevents "..''-style path traversal from
        # reading arbitrary files on disk via this unauthenticated route.
        _frontend_root = _FRONTEND_DIR.resolve()
        candidate = (_frontend_root / path).resolve()
        if candidate.is_relative_to(_frontend_root) and candidate.is_file():
            return FileResponse(str(candidate), headers=_NO_CACHE_HEADERS)
        # Fallback to index.html for SPA routing
        return FileResponse(str(_FRONTEND_DIR / "index.html"), headers=_NO_CACHE_HEADERS)
