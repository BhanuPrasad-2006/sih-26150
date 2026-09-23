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
    DHAV_EXT_HEADER_SIZE,
    DHAV_HEADER_MAGIC,
    DHAV_MIN_HEADER_SIZE,
    DHAV_OFF_CHANNEL,
    DHAV_OFF_DATE,
    DHAV_OFF_EXT_LENGTH,
    DHAV_OFF_FRAME_TYPE,
    DHAV_OFF_SEQUENCE,
    DHAV_OFF_TOTAL_SIZE,
    DHAV_TRAILER_MAGIC,
    DHAV_TRAILER_OFF_LENGTH,
    DHAV_TRAILER_SIZE,
    DHAV_TYPE_VIDEO_DELTA,
    DHAV_TYPE_VIDEO_KEYFRAME,
    EXT4_MAGIC,
    EXT4_SUPERBLOCK_OFFSET,
    HIKV_MASTER_SECTOR_MAGIC,
    HIKV_MASTER_SECTOR_OFFSET,
)

# ── Frame builders ────────────────────────────────────────────────────────────

# Base timestamp: 2024-01-15 10:00:00 UTC
_BASE_TS = int(datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp())


def _encode_dhav_date(ts_seconds: int) -> int:
    """
    Inverse of dahua._decode_dhav_date(): pack a Unix timestamp's UTC calendar
    fields into DHAV's bit-packed date field. The real field can only
    represent years 2000-2063 (6 bits + 2000) — timestamps outside that range
    collapse to a raw 0, which decodes as an invalid calendar date (month=0)
    and is correctly rejected by the validator, mirroring a DVR whose clock
    was never set.
    """
    dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
    if not (2000 <= dt.year <= 2063):
        return 0
    return (
        (dt.second & 0x3F)
        | ((dt.minute & 0x3F) << 6)
        | ((dt.hour & 0x1F) << 12)
        | ((dt.day & 0x1F) << 17)
        | ((dt.month & 0x0F) << 22)
        | (((dt.year - 2000) & 0x3F) << 26)
    )


def make_dhav_frame(
    channel: int,
    seq: int,
    ts_seconds: int,
    ts_ms: int = 0,
    frame_type: int = DHAV_TYPE_VIDEO_KEYFRAME,
    payload_size: int = 512,
    ext_data: bytes = b"",
) -> bytes:
    """
    Build a format-accurate DHAV frame (SYNTHETIC DATA).
    Field positions verified 2026-09 directly against FFmpeg dhav.c source
    (see constants.py header note) — corrects an earlier, wrong layout.
    """
    header_size = DHAV_MIN_HEADER_SIZE + len(ext_data)
    total_size = header_size + payload_size + DHAV_TRAILER_SIZE

    header = bytearray(header_size)
    header[0:4] = DHAV_HEADER_MAGIC
    header[DHAV_OFF_FRAME_TYPE] = frame_type
    header[5] = 0x00  # subtype
    header[DHAV_OFF_CHANNEL] = channel & 0xFF
    header[7] = 0x00  # frame_subnumber
    struct.pack_into("<I", header, DHAV_OFF_SEQUENCE, seq)
    struct.pack_into("<I", header, DHAV_OFF_TOTAL_SIZE, total_size)
    struct.pack_into("<I", header, DHAV_OFF_DATE, _encode_dhav_date(ts_seconds))
    struct.pack_into("<H", header, DHAV_MIN_HEADER_SIZE - DHAV_EXT_HEADER_SIZE, ts_ms)  # timestamp_ms
    header[DHAV_OFF_EXT_LENGTH] = len(ext_data)
    header[DHAV_OFF_EXT_LENGTH + 1] = 0x00  # checksum (not validated)
    header[DHAV_MIN_HEADER_SIZE:header_size] = ext_data

    payload = bytes([0xAB] * payload_size)   # recognisable filler

    trailer = bytearray(DHAV_TRAILER_SIZE)
    trailer[0:4] = DHAV_TRAILER_MAGIC
    struct.pack_into("<I", trailer, DHAV_TRAILER_OFF_LENGTH, total_size)

    return bytes(header) + payload + bytes(trailer)


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
            ftype = DHAV_TYPE_VIDEO_KEYFRAME if i == 0 else DHAV_TYPE_VIDEO_DELTA
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
                               frame_type=DHAV_TYPE_VIDEO_KEYFRAME if i == 0 else DHAV_TYPE_VIDEO_DELTA)
        seq += 1
        ts  += frame_interval_s

    # Gap in content: noise only (simulates deleted index entry)
    buf += make_noise(4096)
    ts += gap_seconds  # time jumps forward

    for i in range(frames_after):
        buf += make_dhav_frame(channel, seq, ts,
                               frame_type=DHAV_TYPE_VIDEO_KEYFRAME if i == 0 else DHAV_TYPE_VIDEO_DELTA)
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


def build_cpplus_image(
    channels: list[int] | None = None,
    frames_per_channel: int = 10,
    frame_interval_s: int = 5,
) -> bytes:
    """
    Build a synthetic CP Plus disk image with CP PLUS identifying banner
    followed by Dahua-compatible DHAV frames.
    SYNTHETIC DATA.
    """
    buf = bytearray()
    buf += b"CP PLUS DVR SYSTEM - ADITYA INFOTECH LTD\x00\x00\x00"
    buf += make_noise(1024)
    buf += build_dahua_image(
        channels=channels,
        frames_per_channel=frames_per_channel,
        frame_interval_s=frame_interval_s,
    )
    return bytes(buf)


def generate_cpplus_image(path: str | Path, **kwargs):
    path = Path(path)
    data = build_cpplus_image(**kwargs)
    path.write_bytes(data)
    return path

if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    print(f"\nGenerating synthetic test images in: {out_dir}")
    print("SYNTHETIC DATA — do not use for accuracy measurement\n")
    generate_all(out_dir)
    print("\nDone.")



# ── Honeywell record builders (layout: arXiv:2605.07430 §5.4.6) ───────────────

def make_honeywell_record(payload: bytes, idr: bool, ts_us: int, width: int = 1920, height: int = 1080) -> bytes:
    """One 20-byte Honeywell 'Custom Header' + Annex B payload."""
    header = bytes([0x82 if idr else 0x02]) + b"\x80\x01\x00" + struct.pack("<HHIQ", width, height, len(payload), ts_us)
    return header + payload


def build_honeywell_stream(payloads: list[tuple[bytes, bool]], start_ts_us: int, interval_us: int = 100_000,
                           width: int = 1920, height: int = 1080) -> bytes:
    """Consecutive records followed by the 20-zero-byte End-of-Channel delimiter."""
    out = bytearray()
    for i, (payload, idr) in enumerate(payloads):
        out += make_honeywell_record(payload, idr, start_ts_us + i * interval_us, width, height)
    out += b"\x00" * 20
    return bytes(out)


def build_gpt_header_image(first_lba: int = 40, total_sectors: int = 4096) -> bytearray:
    """Minimal protective MBR + GPT header + one partition entry (partition 1 at *first_lba*)."""
    img = bytearray(total_sectors * 512)
    img[510:512] = b"\x55\xAA"
    hdr = bytearray(92)
    hdr[0:8] = b"EFI PART"
    struct.pack_into("<Q", hdr, 72, 2)     # partition entries start at LBA 2
    struct.pack_into("<I", hdr, 80, 128)   # number of entries
    struct.pack_into("<I", hdr, 84, 128)   # entry size
    img[512:512 + 92] = hdr
    entry = bytearray(128)
    entry[0:16] = bytes(range(1, 17))      # non-zero type GUID
    struct.pack_into("<Q", entry, 32, first_lba)
    struct.pack_into("<Q", entry, 40, total_sectors - 1)
    img[1024:1024 + 128] = entry
    return img
