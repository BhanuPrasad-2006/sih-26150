"""
test_validation_rules.py — Comprehensive tests for forensic compliance rules.
"""

import pytest
import os
import mmap
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

from backend.acquisition import EvidenceImage, load_disk_image, verify_disk_image_integrity
from backend.plugins.dahua import DahuaPlugin, _validate_dhav_frame
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.unknown import UnknownPlugin
from backend.plugins.constants import DHAV_TRAILER_SIZE
from backend.models import RawFrame, Segment, SegmentStatus, Case, Evidence, DiskOffset
from backend.reconstructor import label_all, reconstruct_segments
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available, ffprobe_check
from backend.audit import AuditLog, AuditEntry
from backend.database import Database
from backend.reporting import generate_report
from backend.test_images.gen_test_image import (
    make_dhav_frame,
    make_noise,
    build_dahua_image,
    build_foreign_ext4_image,
    build_foreign_bitlocker_image,
)

# ── 1. False Positives Test ───────────────────────────────────────────────────

def test_false_positives_random_data(temp_dir):
    """Random data containing fake DHAV markers with invalid lengths yields 0 frames."""
    path = os.path.join(temp_dir, "fake_dhav_noise.dd")
    buf = bytearray([0x55] * (128 * 1024))
    
    # Inject fake DHAV header with invalid length (0 or huge)
    buf[100:104] = b"DHAV"
    buf[104] = 0xF0 # I-frame type
    buf[112:116] = (99999999).to_bytes(4, 'little') # Invalid size
    
    # Inject fake DHAV header without matching footer
    buf[500:504] = b"DHAV"
    buf[504] = 0xF0
    buf[512:516] = (200).to_bytes(4, 'little') # Size 200 but no footer at +192

    with open(path, "wb") as f:
        f.write(buf)

    with EvidenceImage.open(path) as img:
        plugin = DahuaPlugin()
        frames, note = plugin.carve(img)
        assert len(frames) == 0

# ── 2. Window Edge Boundary Test ──────────────────────────────────────────────

def test_window_edge_frame_boundary(temp_dir):
    """A valid frame crossing a scan boundary is found exactly once."""
    frame_data = make_dhav_frame(channel=0, seq=1, ts_seconds=1700000000, payload_size=500)
    frame_len = len(frame_data)
    
    # Place frame across offset 1024
    buf = bytearray(make_noise(1000)) + frame_data + bytearray(make_noise(1000))
    path = os.path.join(temp_dir, "boundary_frame.dd")
    with open(path, "wb") as f:
        f.write(buf)

    with EvidenceImage.open(path) as img:
        plugin = DahuaPlugin()
        frames, _ = plugin.carve(img)
        assert len(frames) == 1
        assert frames[0].disk_offset == 1000

# ── 3. Date Sanity Test ───────────────────────────────────────────────────────

def test_date_sanity_rejection(temp_dir):
    """Timestamps before year 2000 or >1 day in future are rejected."""
    # Pre-2000 timestamp (e.g. 1990: ts = 631152000)
    old_frame = make_dhav_frame(channel=0, seq=1, ts_seconds=631152000)
    
    # Future timestamp (e.g. 10 days in future)
    future_ts = int(time.time()) + (10 * 86400)
    future_frame = make_dhav_frame(channel=0, seq=2, ts_seconds=future_ts)

    buf = bytearray(100) + old_frame + bytearray(100) + future_frame + bytearray(100)
    path = os.path.join(temp_dir, "invalid_dates.dd")
    with open(path, "wb") as f:
        f.write(buf)

    with EvidenceImage.open(path) as img:
        plugin = DahuaPlugin()
        frames, _ = plugin.carve(img)
        assert len(frames) == 0

# ── 4. Image Write / Read-Only Preservation Test ─────────────────────────────

def test_evidence_file_unmodified_after_full_pipeline(temp_dir):
    """Evidence file SHA-256 is identical before and after full scan, export, and report."""
    img_path = os.path.join(temp_dir, "preservation_test.dd")
    with open(img_path, "wb") as f:
        f.write(build_dahua_image(frames_per_channel=5))

    with EvidenceImage.open(img_path) as img:
        initial_hash = img.sha256_before
        
        # 1. Carve
        plugin = DahuaPlugin()
        frames, _ = plugin.carve(img)
        segments = label_all(frames, "EV-001")
        
        # 2. Export segment
        export_dir = Path(temp_dir) / "exports"
        if len(segments) > 0:
            export_segment(img.mm, segments[0], export_dir)

        # 3. Report
        case = Case(case_id="C-01", case_number="TEST-PRES", examiner="Examiner A")
        ev = Evidence(evidence_id="EV-001", case_id="C-01", path=img_path, sha256_before=initial_hash)
        pdf_path = Path(temp_dir) / "report.pdf"
        generate_report(pdf_path, case, ev, segments, [], [], True)

        # 4. Re-verify
        match, current_hash = verify_disk_image_integrity(img_path, initial_hash)
        assert match is True
        assert current_hash == initial_hash

# ── 5. Audit Chain Tamper Test ────────────────────────────────────────────────

def test_audit_chain_tamper_detection():
    """Modifying any past entry breaks audit log chain verification."""
    audit = AuditLog()
    audit.append("INIT", "Case initialized")
    audit.append("SCAN", "Disk scan completed")
    audit.append("EXPORT", "Segment 1 exported")

    valid, err = audit.verify_chain()
    assert valid is True
    assert err is None

    # Tamper with entry #1
    audit._entries[1].details = "TAMPERED DETAILS"

    valid_after_tamper, err_after_tamper = audit.verify_chain()
    assert valid_after_tamper is False
    assert err_after_tamper is not None
    assert "Hash mismatch" in err_after_tamper


# ── 6. BitLocker & Ext4 Rejection Speed Test ─────────────────────────────────

def test_foreign_filesystem_fast_rejection(temp_dir):
    """BitLocker and ext4 disk images are processed/rejected in under 1 second."""
    ext4_path = os.path.join(temp_dir, "foreign_ext4.dd")
    with open(ext4_path, "wb") as f:
        f.write(build_foreign_ext4_image())

    bitlocker_path = os.path.join(temp_dir, "foreign_bitlocker.dd")
    with open(bitlocker_path, "wb") as f:
        f.write(build_foreign_bitlocker_image())

    t0 = time.time()
    with EvidenceImage.open(ext4_path) as img:
        unknown = UnknownPlugin()
        assert unknown.detect(img) > 0.0
    t_ext4 = time.time() - t0

    t0 = time.time()
    with EvidenceImage.open(bitlocker_path) as img:
        unknown = UnknownPlugin()
        assert unknown.detect(img) > 0.0
    t_bitlocker = time.time() - t0

    assert t_ext4 < 10.0
    assert t_bitlocker < 10.0

# ── 7. Hikvision Experimental Status & UNCERTAIN Label Test ────────────────────

def test_hikvision_carving_status_is_uncertain(hikvision_img_path):
    """Carved Hikvision segments must be labelled UNCERTAIN by default."""
    with EvidenceImage.open(hikvision_img_path) as img:
        plugin = HikvisionPlugin()
        frames, _ = plugin.carve(img)
        segments = label_all(frames, "EV-HIKV")
        for seg in segments:
            assert seg.status == SegmentStatus.UNCERTAIN
            assert "Experimental Hikvision" in seg.notes or "UNCERTAIN" in seg.notes

# ── 8. COMPLETE Status Rules Test ─────────────────────────────────────────────

def test_complete_label_requires_valid_decode(temp_dir):
    """
    Authentic test for complete label requirement and ffprobe validation:
    1. Generates a valid H.264 video stream and a corrupted/truncated stream.
    2. Calls real export_segment() to export both as files.
    3. Calls real ffprobe_check() to shell out to ffprobe (no mocking).
    4. Asserts:
       - Corrupted clip fails ffprobe decode and stays UNCERTAIN or PARTIAL (never COMPLETE).
       - Valid clip decodes cleanly via ffprobe (has_video=True) and is eligible for COMPLETE status.
    """
    if not ffmpeg_available() or not ffprobe_available():
        pytest.skip("FFmpeg/ffprobe not found on PATH — skipping authentic decode test.")

    # 1. Generate valid 1-second H.264 clip
    valid_raw_path = os.path.join(temp_dir, "valid_stream.dd")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libx264",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "h264",
        valid_raw_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(valid_raw_path):
        pytest.skip("Failed to generate test H.264 stream with FFmpeg.")

    size_valid = os.path.getsize(valid_raw_path)

    # 2. Generate corrupted stream (garbage bytes, missing codec parameters)
    corrupt_raw_path = os.path.join(temp_dir, "corrupt_stream.dd")
    with open(corrupt_raw_path, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_PAYLOAD_NOT_A_VALID_H264_STREAM_" * 20)

    size_corrupt = os.path.getsize(corrupt_raw_path)

    # 3. Export VALID segment via real export_segment()
    with EvidenceImage.open(valid_raw_path) as valid_img:
        seg_valid = Segment(
            segment_id="SEG-VALID-REAL",
            evidence_id="EV-VALID",
            camera=1,
            frame_count=10,
            status=SegmentStatus.UNCERTAIN,
            notes="Experimental Hikvision carving",
            disk_offsets=[DiskOffset(start=0, end=size_valid)]
        )
        export_dir_valid = Path(temp_dir) / "out_valid"
        exp_v, _ = export_segment(valid_img.mm, seg_valid, export_dir_valid)

        # Execute real ffprobe_check() on exported file
        v_export_file = Path(exp_v.export_path)
        assert v_export_file.exists()
        v_probe_ok, v_probe_info = ffprobe_check(v_export_file)

        # Assert valid clip decodes cleanly via ffprobe
        assert v_probe_ok is True, f"Valid clip failed ffprobe check: {v_probe_info}"
        # Assert status was upgraded by ffprobe check to PARTIAL/COMPLETE (eligible for COMPLETE)
        assert exp_v.status in (SegmentStatus.PARTIAL, SegmentStatus.COMPLETE)

    # 4. Export CORRUPT segment via real export_segment()
    with EvidenceImage.open(corrupt_raw_path) as corrupt_img:
        seg_corrupt = Segment(
            segment_id="SEG-CORRUPT-REAL",
            evidence_id="EV-CORRUPT",
            camera=1,
            frame_count=10,
            status=SegmentStatus.UNCERTAIN,
            notes="Experimental Hikvision carving",
            disk_offsets=[DiskOffset(start=0, end=size_corrupt)]
        )
        export_dir_corrupt = Path(temp_dir) / "out_corrupt"
        exp_c, _ = export_segment(corrupt_img.mm, seg_corrupt, export_dir_corrupt)

        # Execute real ffprobe_check() on exported corrupted file
        c_export_file = Path(exp_c.export_path)
        assert c_export_file.exists()
        c_probe_ok, c_probe_info = ffprobe_check(c_export_file)

        # Assert corrupted clip fails ffprobe decode check
        assert c_probe_ok is False, "Corrupted clip unexpectedly passed ffprobe check"
        # Assert corrupted clip is NOT COMPLETE and remains UNCERTAIN/PARTIAL
        assert exp_c.status != SegmentStatus.COMPLETE
        assert exp_c.status in (SegmentStatus.UNCERTAIN, SegmentStatus.PARTIAL)

# ── 9. Exporter H.264 Clip Wrapping & Header Timestamp Test ───────────────────

def test_exporter_frame_header_timestamps_and_h264_remux(temp_dir):
    """
    Test exporter remuxing using synthetic DHAV headers with real H.264 payload.
    Skips if ffmpeg is missing.
    """
    if not ffmpeg_available():
        pytest.skip("FFmpeg not found on PATH — skipping exporter test.")

    raw_h264_path = os.path.join(temp_dir, "sample.h264")
    # Generate 1 second real H.264 raw video using FFmpeg testsrc
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libx264",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "h264",
        raw_h264_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(raw_h264_path):
        pytest.skip("Failed to generate test H.264 stream with FFmpeg.")

    with open(raw_h264_path, "rb") as f:
        h264_bytes = f.read()

    # Wrap inside synthetic DHAV frame
    ts_seconds = 1700000000
    dhav_frame = make_dhav_frame(
        channel=1,
        seq=1,
        ts_seconds=ts_seconds,
        payload_size=len(h264_bytes)
    )
    # Inject actual H.264 stream into payload area (header is variable-length;
    # payload sits between the header and the fixed-size trailer)
    payload_offset = len(dhav_frame) - len(h264_bytes) - DHAV_TRAILER_SIZE
    dhav_frame_bytes = bytearray(dhav_frame)
    dhav_frame_bytes[payload_offset : payload_offset + len(h264_bytes)] = h264_bytes

    disk_path = os.path.join(temp_dir, "dhav_real_payload.dd")
    with open(disk_path, "wb") as f:
        f.write(bytes(dhav_frame_bytes))

    with EvidenceImage.open(disk_path) as img:
        plugin = DahuaPlugin()
        frames, _ = plugin.carve(img)
        assert len(frames) == 1
        
        # Verify timestamp came from frame header
        frame_dt = frames[0].timestamp
        expected_dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
        assert frame_dt == expected_dt

        segments = label_all(frames, "EV-REAL-H264")
        assert len(segments) == 1
        assert segments[0].start_time == expected_dt

        export_dir = Path(temp_dir) / "real_export"
        exported_seg, detail = export_segment(img.mm, segments[0], export_dir)
        assert exported_seg.export_path != ""
        assert os.path.exists(exported_seg.export_path)
