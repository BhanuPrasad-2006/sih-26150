"""
main.py — FastAPI application entry point.

Binds ONLY to 127.0.0.1 (localhost). No external access. No telemetry.
Serves the frontend at / and API at /api.

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
import sqlite3
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import aiofiles
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.acquisition import AcquisitionError, EvidenceImage
from backend.audit import AuditLog
from backend.database import (
    Database,
    get_case_export_dir,
    get_case_report_dir,
)
from backend.exporter import export_segment
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
from backend.plugins.dahua import DahuaPlugin
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.matrix import MatrixPlugin
from backend.plugins.unknown import UnknownPlugin
from backend.plugins.uniview import UniviewPlugin
from backend.reconstructor import label_all
from backend.reporting import generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger("main")

# ── Global state ──────────────────────────────────────────────────────────────

db: Database = Database()
# Per-case: {case_id → asyncio.Queue[ScanProgress]}
_progress_queues: dict[str, asyncio.Queue] = {}
# Per-case: open EvidenceImage (kept alive for export)
_open_images: dict[str, EvidenceImage] = {}
# Per-case: AuditLog
_audit_logs: dict[str, AuditLog] = {}
# Per-case scan tasks (for pause/resume via simple event)
_scan_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    if not hasattr(db, "_path"):
        db = Database()
    log.info("Database initialised at %s", db._path)
    yield

    # Close any open images on shutdown
    for img in list(_open_images.values()):
        try:
            img.close()
        except Exception:
            pass


app = FastAPI(
    title="SIH26150 DVR/NVR Forensic Tool",
    version="1.0.0-dev",
    docs_url="/api/docs",
    lifespan=lifespan,
)

# ── Plugin registry ───────────────────────────────────────────────────────────

_PLUGINS = [DahuaPlugin(), HikvisionPlugin(), UniviewPlugin(), MatrixPlugin()]


def _detect_brand(img: EvidenceImage) -> tuple[str, str, float, Any]:
    """Run all plugins' detect() and return (brand, version, confidence, plugin)."""
    best_conf   = 0.0
    best_plugin = UnknownPlugin()
    for plugin in _PLUGINS:
        try:
            conf = plugin.detect(img)
        except Exception:
            conf = 0.0
        if conf > best_conf:
            best_conf   = conf
            best_plugin = plugin
    # display_name carries UI/report labels (e.g. "detection-only / unverified").
    return (
        best_plugin.display_name,
        best_plugin.version_hint(),
        best_conf,
        best_plugin,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(case_id: str, action: str, details: str = "") -> None:
    audit = _audit_logs.get(case_id)
    if audit:
        entry = audit.append(action, details)
        try:
            db.save_audit_entry(entry)
        except Exception:
            pass


async def _push_progress(case_id: str, prog: ScanProgress) -> None:
    q = _progress_queues.get(case_id)
    if q:
        await q.put(prog)


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
        ev.is_synthetic  = "synthetic" in ev.path.lower()
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

        if confidence < MIN_PLUGIN_CONFIDENCE:
            await push(ScanPhase.ERROR,
                message=f"Brand confidence {confidence:.0%} is below threshold "
                        f"({MIN_PLUGIN_CONFIDENCE:.0%}). "
                        f"Disk may be unsupported, encrypted, or not a DVR/NVR disk. "
                        f"Details: {plugin.version_hint()}"
            )
            return

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

        all_frames = index_frames + carved_frames
        await push(ScanPhase.CARVING, 80,
                   f"Carving done: {len(carved_frames)} frames. {carve_note}")

        # ── Step 5: reconstruct ────────────────────────────────────────────
        await push(ScanPhase.RECONSTRUCTING, 82, "Grouping by camera and sorting by time…")
        segments = await asyncio.to_thread(label_all, all_frames, evidence_id)
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
        q = _progress_queues.get(case_id)
        if q:
            await q.put(None)  # sentinel


# ── API routes ────────────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    case_number: str
    examiner: str
    notes: Optional[str] = None


class LoadEvidenceRequest(BaseModel):
    path: str  # absolute path to .dd / .img file on the examiner's machine


@app.post("/api/cases", response_model=Case)
async def create_case(req: CreateCaseRequest):
    case = Case(case_number=req.case_number, examiner=req.examiner, notes=req.notes)
    try:
        result = await asyncio.to_thread(db.create_case, case)
    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            f"Case number '{req.case_number}' already exists. "
            "Each case must have a unique case number."
        )
    _audit_logs[case.case_id] = AuditLog()
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

    # Collect segments for all evidence items belonging to this case
    segments: list = []
    log_events: list = []
    for ev in evidence:
        segs = await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)
        segments.extend(segs)
        les = await asyncio.to_thread(db.list_log_events, ev.evidence_id)
        log_events.extend(les)

    # Audit entries from in-memory log (re-hydrate from DB if server was restarted)
    audit_log = _audit_logs.get(case_id, AuditLog())
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

    ev = Evidence(case_id=case_id, path=str(path))
    ev = await asyncio.to_thread(db.save_evidence, ev)
    _audit(case_id, "evidence_loaded", f"path={req.path}")

    # Ensure audit log and progress queue exist
    if case_id not in _audit_logs:
        _audit_logs[case_id] = AuditLog()
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
async def list_segments(case_id: str):
    evs = await asyncio.to_thread(db.list_evidence_for_case, case_id)
    if not evs:
        return []
    ev = evs[-1]
    return await asyncio.to_thread(db.list_segments_for_evidence, ev.evidence_id)


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


@app.get("/api/cases/{case_id}/verify")
async def verify_evidence(case_id: str):
    img = _open_images.get(case_id)
    if not img:
        raise HTTPException(400, "Evidence image is not loaded")
    unchanged = await asyncio.to_thread(img.verify_unchanged)
    _audit(case_id, "verify_requested", f"unchanged={unchanged}")
    return {"unchanged": unchanged, "sha256": img.sha256_before}


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
    audit_log = _audit_logs.get(case_id, AuditLog())
    chain_ok, _ = audit_log.verify_chain()
    entries   = audit_log.export_entries()
    from backend.models import AuditEntry
    audit_entries = [AuditEntry(**e) for e in entries]

    report_dir = get_case_report_dir(case_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pdf = report_dir / f"report_{ts}.pdf"

    await asyncio.to_thread(
        generate_report, pdf, case, ev, segments, log_evts, audit_entries, chain_ok
    )
    _audit(case_id, "report_generated", str(pdf))
    return FileResponse(str(pdf), media_type="application/pdf",
                        filename=f"report_case_{case.case_number}_{ts}.pdf")


@app.get("/api/cases/{case_id}/audit")
async def get_audit(case_id: str):
    audit_log = _audit_logs.get(case_id, AuditLog())
    chain_ok, error = audit_log.verify_chain()
    return {"chain_intact": chain_ok, "error": error, "entries": audit_log.export_entries()}


# ── Serve frontend static files ───────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(_FRONTEND_DIR / "index.html"))

    @app.get("/{path:path}")
    async def serve_static(path: str):
        file_path = _FRONTEND_DIR / path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Fallback to index.html for SPA routing
        return FileResponse(str(_FRONTEND_DIR / "index.html"))
