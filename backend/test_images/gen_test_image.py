"""
gen_test_image.py — Synthetic disk image generator for unit tests.

IMPORTANT — SYNTHETIC DATA LABEL
All images produced here are labelled "synthetic" in their filename and content.
Numbers from tests on synthetic images MUST NOT be reported as real accuracy results.
This generator exists only to make the test suite runnable without a real recorder.

Images produced:
  synthetic_dahua.img          — DHAV frames on multiple channels with a gap
  synthetic_hikvision.img      — Hikvision master sector magic at 0x200
  synthetic_dahua_deleted.img  — DHAV frames where some are only reachable by carving
  synthetic_foreign_ext4.img   — ext4 magic (should be rejected by both plugins)
  synthetic_bitlocker.img      — BitLocker magic (should be rejected)

Usage:
  python backend/test_images/gen_test_image.py [output_dir]
  (default output_dir: backend/test_images/)
"""

from __future__ import annotations

import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.plugins.constants import (
    BITLOCKER_MAGIC,
    BITLOCKER_MAGIC_OFFSET,
    DHAV_FOOTER_MAGIC,
    DHAV_FOOTER_OFF_LENGTH,
    DHAV_FOOTER_SIZE,
    DHAV_HEADER_MAGIC,
    DHAV_HEADER_SIZE,
    DHAV_OFF_CHANNEL,
    DHAV_OFF_FRAME_TYPE,
    DHAV_OFF_SEQUENCE,
    DHAV_OFF_TIMESTAMP_MS,
    DHAV_OFF_TIMESTAMP_S,
    DHAV_OFF_TOTAL_SIZE,
    DHAV_TYPE_VIDEO_IFRAME,
    DHAV_TYPE_VIDEO_PFRAME,
    EXT4_MAGIC,
    EXT4_SUPERBLOCK_OFFSET,
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
)

# ── Frame builders ────────────────────────────────────────────────────────────

# Base timestamp: 2024-01-15 10:00:00 UTC
_BASE_TS = int(datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp())


def make_dhav_frame(
    channel: int,
    seq: int,
    ts_seconds: int,
    ts_ms: int = 0,
    frame_type: int = DHAV_TYPE_VIDEO_IFRAME,
    payload_size: int = 512,
) -> bytes:
    """
    Build a syntactically valid DHAV frame (SYNTHETIC DATA).
    All field positions verified from FFmpeg dhav.c.
    """
    total_size = DHAV_HEADER_SIZE + payload_size + DHAV_FOOTER_SIZE

    header = bytearray(DHAV_HEADER_SIZE)
    header[0:4] = DHAV_HEADER_MAGIC
    header[DHAV_OFF_FRAME_TYPE]  = frame_type
    header[DHAV_OFF_SUBTYPE := 5] = 0x00
    struct.pack_into("<H", header, DHAV_OFF_CHANNEL,      channel)
    struct.pack_into("<I", header, DHAV_OFF_SEQUENCE,     seq)
    struct.pack_into("<I", header, DHAV_OFF_TOTAL_SIZE,   total_size)
    struct.pack_into("<I", header, DHAV_OFF_TIMESTAMP_S,  ts_seconds)
    struct.pack_into("<H", header, DHAV_OFF_TIMESTAMP_MS, ts_ms)

    payload = bytes([0xAB] * payload_size)   # recognisable filler

    footer = bytearray(DHAV_FOOTER_SIZE)
    footer[0:4] = DHAV_FOOTER_MAGIC
    struct.pack_into("<I", footer, DHAV_FOOTER_OFF_LENGTH, total_size)

    return bytes(header) + payload + bytes(footer)


def make_noise(size: int) -> bytes:
    """Return a block of pseudo-random-looking bytes (no DHAV markers)."""
    # Use 0xCC filler — avoids accidentally creating b'DHAV' or b'dhav'
    return bytes([0xCC] * size)


# ── Image builders ────────────────────────────────────────────────────────────

def build_dahua_image(
    channels: list[int] = None,
    frames_per_channel: int = 10,
    frame_interval_s: int = 5,
) -> bytes:
    """
    Build a synthetic Dahua-like image with interleaved DHAV frames.
    Two channels by default: camera 0 and camera 1.
    Frame timestamps start at _BASE_TS and advance by frame_interval_s per frame.
    The image has leading noise, interleaved frames, and trailing noise.
    SYNTHETIC DATA — do not use for accuracy measurement.
    """
    if channels is None:
        channels = [0, 1]

    buf = bytearray()
    buf += make_noise(1024)  # leading noise

    seq = {ch: 0 for ch in channels}
    ts  = {ch: _BASE_TS + ch * 1 for ch in channels}  # slight offset per channel

    for i in range(frames_per_channel):
        for ch in channels:
            ftype = DHAV_TYPE_VIDEO_IFRAME if i == 0 else DHAV_TYPE_VIDEO_PFRAME
            buf += make_dhav_frame(
                channel=ch,
                seq=seq[ch],
                ts_seconds=ts[ch],
                frame_type=ftype,
                payload_size=256,
            )
            seq[ch] += 1
            ts[ch]  += frame_interval_s
        buf += make_noise(128)  # inter-frame noise

    buf += make_noise(1024)  # trailing noise
    return bytes(buf)


def build_dahua_with_gap_image(
    channel: int = 0,
    frames_before: int = 8,
    frames_after: int = 6,
    gap_seconds: int = 30,  # time gap > GAP_T_MAX → new session
    frame_interval_s: int = 2,
) -> bytes:
    """
    Build a synthetic Dahua image simulating a deleted-and-recovered recording.
    Frames before the gap represent a normal recording.
    Frames after the gap represent a second session separated by a large time jump.
    SYNTHETIC DATA.
    """
    buf = bytearray()
    buf += make_noise(512)

    seq = 0
    ts  = _BASE_TS

    for i in range(frames_before):
        buf += make_dhav_frame(channel, seq, ts,
                               frame_type=DHAV_TYPE_VIDEO_IFRAME if i == 0 else DHAV_TYPE_VIDEO_PFRAME)
        seq += 1
        ts  += frame_interval_s

    # Gap in content: noise only (simulates deleted index entry)
    buf += make_noise(4096)
    ts += gap_seconds  # time jumps forward

    for i in range(frames_after):
        buf += make_dhav_frame(channel, seq, ts,
                               frame_type=DHAV_TYPE_VIDEO_IFRAME if i == 0 else DHAV_TYPE_VIDEO_PFRAME)
        seq += 1
        ts  += frame_interval_s

    buf += make_noise(512)
    return bytes(buf)


def build_hikvision_image() -> bytes:
    """
    Build a synthetic Hikvision-like image with the master sector magic at 0x200.
    Verified: HIKVISION@HANGZHOU at offset 0x200 — Han 2015.
    SYNTHETIC DATA — no actual HIKB-TREE index or data blocks are created.
    """
    buf = bytearray(0x200 + 512 + 1024)  # master sector area
    buf[HIKV_MASTER_SECTOR_OFFSET: HIKV_MASTER_SECTOR_OFFSET + len(HIKV_MASTER_SECTOR_MAGIC)] = (
        HIKV_MASTER_SECTOR_MAGIC
    )
    buf += make_noise(1024)
    return bytes(buf)


def build_foreign_ext4_image() -> bytes:
    """
    Build a synthetic ext4 image.
    ext4 superblock magic 0xEF53 at offset 0x438.
    Should be rejected by both DVR plugins.
    SYNTHETIC DATA.
    """
    size = EXT4_SUPERBLOCK_OFFSET + 4 + 1024
    buf = bytearray(size)
    buf[EXT4_SUPERBLOCK_OFFSET: EXT4_SUPERBLOCK_OFFSET + 2] = EXT4_MAGIC
    return bytes(buf)


def build_foreign_bitlocker_image() -> bytes:
    """
    Build a synthetic BitLocker-like image.
    '-FVE-FS-' at offset 3.
    Should be detected as encrypted by UnknownPlugin.
    SYNTHETIC DATA.
    """
    size = BITLOCKER_MAGIC_OFFSET + 16 + 512
    buf  = bytearray(size)
    buf[BITLOCKER_MAGIC_OFFSET: BITLOCKER_MAGIC_OFFSET + 8] = BITLOCKER_MAGIC
    return bytes(buf)


# ── Writer ────────────────────────────────────────────────────────────────────

_IMAGES: dict[str, tuple[str, object]] = {
    "synthetic_dahua.img":          ("Standard Dahua multi-channel", build_dahua_image),
    "synthetic_dahua_gap.img":      ("Dahua with time gap (deleted recording simulation)", build_dahua_with_gap_image),
    "synthetic_hikvision.img":      ("Hikvision master sector only", build_hikvision_image),
    "synthetic_foreign_ext4.img":   ("Foreign ext4 (should be rejected)", build_foreign_ext4_image),
    "synthetic_bitlocker.img":      ("Foreign BitLocker (should be rejected)", build_foreign_bitlocker_image),
}


def generate_all(output_dir: Path) -> dict[str, Path]:
    """Generate all synthetic images and return {name → path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created = {}
    for filename, (desc, builder) in _IMAGES.items():
        path = output_dir / filename
        data = builder()
        path.write_bytes(data)
        print(f"  [SYNTHETIC] {filename:40s}  {len(data):>9,} bytes  — {desc}")
        created[filename] = path
    return created


def generate_dahua_image(path: str | Path, num_frames: int = 20, include_gap: bool = True):
    path = Path(path)
    if include_gap:
        data = build_dahua_with_gap_image()
    else:
        data = build_dahua_image(frames_per_channel=num_frames // 2)
    path.write_bytes(data)

def generate_hikvision_image(path: str | Path):
    path = Path(path)
    data = build_hikvision_image()
    path.write_bytes(data)

def generate_foreign_image(path: str | Path, fs_type: str = "ext4"):
    path = Path(path)
    if fs_type == "bitlocker":
        data = build_foreign_bitlocker_image()
    else:
        data = build_foreign_ext4_image()
    path.write_bytes(data)

if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    print(f"\nGenerating synthetic test images in: {out_dir}")
    print("SYNTHETIC DATA — do not use for accuracy measurement\n")
    generate_all(out_dir)
    print("\nDone.")

