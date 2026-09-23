"""
models.py — Pydantic data models and plain dataclasses.

Pydantic models are used for API serialisation.
RawFrame is a lightweight dataclass used only during scanning (not stored in DB directly).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class SegmentStatus(str, Enum):
    """
    Labelling rules (PRD §4.4):
      COMPLETE  — all frame checks pass, ffprobe decodes cleanly, and (if the
                  original is known) hashes match.
      PARTIAL   — valid frames found but there are gaps, missing frames or the
                  recording is unfinished. Gaps are listed with times.
      UNCERTAIN — some checks failed (e.g. markers found but timestamps look wrong).
                  Never presented as reliable.
    """
    COMPLETE  = "COMPLETE"
    PARTIAL   = "PARTIAL"
    UNCERTAIN = "UNCERTAIN"


class ScanPhase(str, Enum):
    IDLE          = "IDLE"
    HASHING       = "HASHING"
    DETECTING     = "DETECTING"
    INDEX_READ    = "INDEX_READ"
    CARVING       = "CARVING"
    RECONSTRUCTING = "RECONSTRUCTING"
    DONE          = "DONE"
    ERROR         = "ERROR"
    PAUSED        = "PAUSED"


# ── API / DB models ────────────────────────────────────────────────────────────

class Case(BaseModel):
    case_id:     str = Field(default_factory=lambda: str(uuid4()))
    case_number: str
    examiner:    str
    notes:       Optional[str] = None
    created_at:  str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CaseDetail(Case):
    """
    Extended Case response that always includes child arrays.
    The frontend can safely call .length / iterate without undefined checks.
    """
    evidence:    list["Evidence"]    = Field(default_factory=list)
    segments:    list["Segment"]     = Field(default_factory=list)
    log_events:  list["LogEvent"]    = Field(default_factory=list)
    audit:       list["AuditEntry"]  = Field(default_factory=list)


class Evidence(BaseModel):
    evidence_id:    str = Field(default_factory=lambda: str(uuid4()))
    case_id:        str
    path:           str
    size_bytes:     Optional[int]    = None
    sha256_before:  Optional[str]    = None
    md5_before:     Optional[str]    = None
    sha256_after:   Optional[str]    = None
    brand:          Optional[str]    = None
    brand_version:  Optional[str]    = None
    confidence:     Optional[float]  = None
    is_synthetic:   bool             = False  # True when path is a generated test image
    created_at:     str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Examiner-supplied device clock offset from UTC, in minutes (e.g. +330 for
    # IST). Carved timestamps are parsed as raw device-reported values (TO
    # VERIFY — see format sheets); this is never inferred automatically, only
    # set explicitly by the examiner, and is used to normalize timestamps for
    # cross-evidence correlation and reporting. None = not specified.
    device_utc_offset_minutes: Optional[int] = None


class DiskOffset(BaseModel):
    """Start and end byte offsets of one contiguous run of frames on the disk image."""
    start: int
    end:   int


class Segment(BaseModel):
    segment_id:   str = Field(default_factory=lambda: str(uuid4()))
    evidence_id:  str
    camera:       int
    start_time:   Optional[datetime] = None
    end_time:     Optional[datetime] = None
    disk_offsets: list[DiskOffset]   = Field(default_factory=list)
    frame_count:  int                = 0
    status:       SegmentStatus      = SegmentStatus.UNCERTAIN
    export_path:     Optional[str]      = None
    sha256:          Optional[str]      = None
    notes:           Optional[str]      = None   # e.g. "experimental carving — TO VERIFY"
    motion_detected: Optional[bool]     = None
    motion_details:  Optional[str]      = None
    face_detected:          Optional[bool] = None
    face_detection_details: Optional[str]  = None


class LogEvent(BaseModel):
    event_id:        str = Field(default_factory=lambda: str(uuid4()))
    evidence_id:     str
    event_timestamp: Optional[datetime] = None
    event_type:      str                = ""  # "format" | "recording" | "login" | "unknown"
    detail:          str                = ""
    source_offset:   Optional[int]      = None


class AuditEntry(BaseModel):
    entry_id:      str = Field(default_factory=lambda: str(uuid4()))
    created_at:    str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action:        str
    details:       str = ""
    previous_hash: str = ""   # "" for the first entry
    entry_hash:    str = ""   # set by AuditLog after construction


class ScanProgress(BaseModel):
    """Sent over SSE to the frontend."""
    phase:         ScanPhase = ScanPhase.IDLE
    percent:       float     = 0.0
    frames_found:  int       = 0
    bytes_done:    int       = 0
    total_bytes:   int       = 0
    eta_seconds:   Optional[float] = None
    message:       str       = ""
    error:         Optional[str]   = None


# ── Internal scanning dataclass (not stored in DB) ────────────────────────────

@dataclass
class RawFrame:
    """
    A single validated DHAV or NAL frame as found by carving.
    Used internally during scanning; the reconstructor groups these into Segments.
    """
    brand:        str      # "dahua" | "hikvision"
    camera:       int
    sequence:     int
    timestamp:    Optional[datetime]
    disk_offset:  int      # byte offset in the image file where this frame starts
    frame_size:   int      # total bytes (header + payload + footer)
    frame_type:   int      # raw type byte (e.g. 0xF0)
    is_keyframe:  bool

    @property
    def disk_offset_end(self) -> int:
        return self.disk_offset + self.frame_size
