"""
exporter.py — Export carved segments to MP4 and hash every output file.

Rules (PRD §2.4 step 6, §FR-13, §FR-14):
  - Always use -c copy (never re-encode).
  - Timestamps in the MP4 container come from the frame headers stored in the DB,
    not from the MP4 duration (MP4 duration is unreliable for reassembled streams).
  - Try FFmpeg's DHAV demuxer first for Dahua segments.
  - If FFmpeg is not on PATH, export the raw stream and warn clearly.
  - Run ffprobe on every output. A segment is upgraded to PARTIAL (from UNCERTAIN)
    if ffprobe decodes the stream cleanly. COMPLETE is only set when all checks
    pass AND (if the original is known) hashes match — the caller handles that.
  - Hash every exported file with SHA-256 and store in the Segment record.

Disk offsets note:
  RawFrame.frame_size is a placeholder (4 bytes) for Hikvision NAL candidates.
  For Dahua frames, frame_size = header + payload + footer (verified).
  The exporter writes only verified-size frames to the output file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from backend.models import Segment, SegmentStatus

log = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def hash_file(path: Path) -> str:
    """Compute SHA-256 of a file. Returns hex string."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe_check(path: Path) -> tuple[bool, dict]:
    """
    Run ffprobe on *path* and return (success, info_dict).
    success=True means ffprobe found at least one decodable video or audio stream.
    """
    if not ffprobe_available():
        return False, {"error": "ffprobe not on PATH"}
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "stream=codec_name,codec_type,duration,nb_frames",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return False, {"stderr": result.stderr[:500]}
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        return (has_video or has_audio), data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as exc:
        return False, {"error": str(exc)}


def extract_raw_stream(
    mm,
    segment: Segment,
    output_path: Path,
) -> bool:
    """
    Write the raw bytes from disk_offsets to output_path.
    Returns True on success.
    Only Dahua frames with verified sizes are written; placeholder NAL entries (size=4)
    are skipped.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as out:
            for offset in segment.disk_offsets:
                size = offset.end - offset.start
                if size <= 4:
                    # Placeholder NAL entry — skip (Hikvision experimental)
                    continue
                chunk = mm[offset.start : offset.end]
                out.write(chunk)
        return output_path.stat().st_size > 0
    except Exception as exc:
        log.warning("extract_raw_stream failed: %s", exc)
        return False


def remux_dhav_to_mp4(raw_path: Path, mp4_path: Path) -> tuple[bool, str]:
    """
    Use FFmpeg's DHAV demuxer to remux the raw DHAV stream to MP4.
    -c copy: no re-encoding.
    Returns (success, stderr_summary).
    """
    if not ffmpeg_available():
        return False, "ffmpeg not on PATH"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "dhav",
                "-i", str(raw_path),
                "-c", "copy",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0, result.stderr[-500:] if result.stderr else ""
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timed out (>300 s)"
    except Exception as exc:
        return False, str(exc)


def remux_h264_to_mp4(raw_path: Path, mp4_path: Path) -> tuple[bool, str]:
    """
    Remux a carved Hikvision stream to MP4 with FFmpeg (-c copy, no re-encoding).
    The carver emits either an MPEG program stream (starts with 00 00 01 BA —
    let FFmpeg autodetect it) or a raw H.264 Annex B stream (-f h264).
    Returns (success, stderr_summary).
    """
    if not ffmpeg_available():
        return False, "ffmpeg not on PATH"
    try:
        with open(raw_path, "rb") as fh:
            is_program_stream = fh.read(4) == b"\x00\x00\x01\xBA"
        input_fmt = [] if is_program_stream else ["-f", "h264"]
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                *input_fmt,
                "-i", str(raw_path),
                "-c", "copy",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0, result.stderr[-500:] if result.stderr else ""
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timed out (>300 s)"
    except Exception as exc:
        return False, str(exc)


def export_segment(
    mm,
    segment: Segment,
    output_dir: Path,
) -> tuple[Segment, dict]:
    """
    Full export pipeline for one segment:
      1. Write raw stream bytes.
      2. Try to remux to MP4 (DHAV demuxer for Dahua, H.264 parser for Hikvision).
      3. Run ffprobe on the MP4.
      4. Hash the final file.
      5. Update segment.export_path, segment.sha256, and segment.status.
      6. Return updated segment and a detail dict for the audit log.

    The segment status is NEVER upgraded to COMPLETE here.
    COMPLETE requires a known-answer hash match (the caller handles that).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    detail: dict = {"segment_id": segment.segment_id, "camera": segment.camera}
    _n = (segment.notes or "").lower()
    # Standard-stream carved brands export raw Annex B / MPEG-PS, not DHAV.
    brand = "hikvision" in _n or "generic stream carving" in _n or "honeywell record carving" in _n

    if not segment.disk_offsets:
        # No byte ranges were recorded for this segment (e.g. legacy segments
        # saved by the pre-2026-09 Hikvision carver, which recorded only NAL
        # start-code positions). Report this upfront instead of attempting
        # extraction and failing with a generic "empty raw stream" message.
        detail["error"] = (
            "No exportable frame data recorded for this segment — no verified "
            "byte ranges were saved during carving, so nothing can be safely "
            "written as video. Re-run the scan to re-carve this evidence."
        )
        segment.notes = (segment.notes or "") + " | Export unavailable: no verified frame boundaries."
        return segment, detail

    # Step 1: extract raw bytes
    raw_path = output_dir / f"{segment.segment_id}_raw.bin"
    ok = extract_raw_stream(mm, segment, raw_path)
    if not ok or not raw_path.exists() or raw_path.stat().st_size == 0:
        detail["error"] = "raw stream extraction produced empty file"
        segment.notes = (segment.notes or "") + " | Export failed: empty raw stream."
        return segment, detail

    # Step 2: remux to MP4
    mp4_path = output_dir / f"{segment.segment_id}.mp4"
    if brand:
        ok, ffmpeg_err = remux_h264_to_mp4(raw_path, mp4_path)
    else:
        ok, ffmpeg_err = remux_dhav_to_mp4(raw_path, mp4_path)

    if not ok:
        # Fall back: serve the raw stream as the export
        log.warning("FFmpeg remux failed for %s: %s", segment.segment_id, ffmpeg_err)
        mp4_path = raw_path
        detail["ffmpeg_warning"] = f"Remux failed ({ffmpeg_err}); raw stream exported instead."
        segment.notes = (segment.notes or "") + f" | FFmpeg remux failed: {ffmpeg_err[:120]}"

    # Step 3: ffprobe check
    probe_ok, probe_info = ffprobe_check(mp4_path)
    detail["ffprobe"] = probe_info
    detail["ffprobe_valid"] = probe_ok
    if probe_ok and segment.status == SegmentStatus.UNCERTAIN:
        segment.status = SegmentStatus.PARTIAL
        segment.notes = (segment.notes or "") + " | ffprobe decoded stream — upgraded to PARTIAL."

    # Step 4: hash
    segment.sha256 = hash_file(mp4_path)
    segment.export_path = str(mp4_path)
    detail["sha256"] = segment.sha256
    detail["export_path"] = segment.export_path

    # Clean up raw file if we successfully remuxed to MP4
    if mp4_path != raw_path and raw_path.exists():
        try:
            raw_path.unlink()
        except Exception:
            pass

    return segment, detail
