"""
test_wfs.py — Tests for WFS (Xiongmai / White-label DVR) plugin.
"""

import os
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.plugins.registry import detect_brand
from backend.plugins.wfs import WFSPlugin, parse_wfs_epoch_timestamp
from backend.reconstructor import label_all


def test_wfs_timestamp_decoding():
    # 2026-10-09 00:00:00 UTC
    dt_target = datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc)
    epoch_val = int(dt_target.timestamp())

    parsed = parse_wfs_epoch_timestamp(epoch_val)
    assert parsed == dt_target

    # Out of range timestamp returns None
    assert parse_wfs_epoch_timestamp(0) is None
    assert parse_wfs_epoch_timestamp(3000000000) is None


def test_wfs_detection_and_carving(tmp_path):
    img_path = tmp_path / "wfs_dump.img"

    # Construct synthetic WFS disk image
    superblock = b"WFS0.2" + b"\x00" * 506  # 512 bytes sector 0
    noise = os.urandom(1024)

    # Construct 2 WFS frame records
    # [0:3]=b"WFS", [3]=0x02, [4]=channel 1, [5]=I-frame (0), [6:8]=0, [8:12]=len, [12:16]=epoch
    target_dt = datetime(2026, 10, 9, 5, 30, 0, tzinfo=timezone.utc)
    target_epoch = int(target_dt.timestamp())

    frame1_payload = b"\x00\x00\x00\x01\x67\x42\x00\x1E" + b"\xAA" * 100
    frame1_hdr = struct.pack("<3sBBBHII", b"WFS", 2, 1, 0, 0, len(frame1_payload) + 16, target_epoch)
    frame1 = frame1_hdr + frame1_payload

    # Frame 2: Channel 2, P-frame (1)
    frame2_payload = b"\x00\x00\x00\x01\x41\x00" + b"\xBB" * 80
    frame2_hdr = struct.pack("<3sBBBHII", b"WFS", 2, 2, 1, 0, len(frame2_payload) + 16, target_epoch + 1)
    frame2 = frame2_hdr + frame2_payload

    tail = b"\xFF" * 1024

    img_path.write_bytes(superblock + noise + frame1 + frame2 + tail)

    with EvidenceImage.open(img_path) as img:
        brand_name, version, conf, plugin = detect_brand(img)
        assert conf >= 0.9
        assert "WFS" in brand_name

        frames, note = plugin.carve(img)
        assert len(frames) == 2
        assert frames[0].camera == 1
        assert frames[0].is_keyframe is True
        assert frames[0].timestamp == target_dt

        assert frames[1].camera == 2
        assert frames[1].is_keyframe is False
        assert frames[1].timestamp == datetime(2026, 10, 9, 5, 30, 1, tzinfo=timezone.utc)

        # Label segments
        segs = label_all(frames, "ev-wfs")
        assert len(segs) == 2
