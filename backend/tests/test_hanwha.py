"""
test_hanwha.py — Tests for Hanwha Vision / Samsung Techwin plugin.
"""

import os
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.plugins.hanwha import HanwhaPlugin, parse_hanwha_timestamp
from backend.plugins.registry import detect_brand


def test_hanwha_timestamp_decoding():
    dt_target = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    epoch_val = int(dt_target.timestamp())

    assert parse_hanwha_timestamp(epoch_val) == dt_target
    assert parse_hanwha_timestamp(0) is None


def test_hanwha_detection_and_carving(tmp_path):
    img_path = tmp_path / "hanwha_dump.img"

    # Superblock starting with SSF1.0
    superblock = b"SSF1.0" + b"\x00" * 506
    noise = os.urandom(512)

    target_dt = datetime(2026, 10, 9, 6, 0, 0, tzinfo=timezone.utc)
    target_epoch = int(target_dt.timestamp())

    frame1_payload = b"\x00\x00\x00\x01\x67\x42\x00\x1E" + b"\xCC" * 60
    frame1_hdr = struct.pack("<3sBBBHII", b"SEC", 1, 3, 0, 0, len(frame1_payload) + 16, target_epoch)
    frame1 = frame1_hdr + frame1_payload

    img_path.write_bytes(superblock + noise + frame1 + b"\x00" * 512)

    with EvidenceImage.open(img_path) as img:
        brand_name, version, conf, plugin = detect_brand(img)
        assert conf >= 0.85
        assert "Hanwha" in brand_name

        frames, note = plugin.carve(img)
        assert len(frames) == 1
        assert frames[0].camera == 3
        assert frames[0].is_keyframe is True
        assert frames[0].timestamp == target_dt
