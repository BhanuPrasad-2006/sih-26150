#!/usr/bin/env python3
"""
prepare_test_evidence.py — Turn any real CCTV video into a forensic disk image (.dd)
simulating an unindexed / deleted Hikvision recording.

Usage:
    python tools/prepare_test_evidence.py <path_to_ground_truth_video> [output_image.dd]
"""

import os
import sys
import shutil
import hashlib
import subprocess
from pathlib import Path

# Constants for Hikvision Master Sector
HIKV_MASTER_SECTOR_MAGIC = b"HIKVISION@HANGZHOU"
HIKV_MASTER_SECTOR_OFFSET = 0x200  # Sector 1 (byte 512)

def generate_decoys() -> bytes:
    """Generate non-video decoy bytes and random noise mimicking unallocated disk space."""
    rnd = os.urandom(2048)
    return (
        b"\xCC" * 512
        + b"\x00\x00\x01\x67\x42\x00\x1e" + rnd[:500]       # Incomplete decoy header
        + b"\x00\x00\x01\xBA\x44\x00\x04\x00\x04\x01" + rnd[500:1000] # Bogus pack
        + b"\xCC" * 512
        + rnd[1000:]
        + b"\xCC" * 512
    )

def extract_stream_bytes(input_video: Path) -> bytes:
    """Extract elementary H.264 Annex-B or MPEG-PS stream bytes from the video using ffmpeg."""
    temp_stream = input_video.parent / f"_temp_{input_video.stem}.h264"
    
    # Try direct copy to h264 annex B
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(input_video),
        "-c:v", "copy",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "h264",
        str(temp_stream)
    ]
    res = subprocess.run(cmd)
    
    if res.returncode != 0 or not temp_stream.exists() or temp_stream.stat().st_size == 0:
        # Fallback: re-encode to baseline h264 stream
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(input_video),
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-f", "h264",
            str(temp_stream)
        ]
        subprocess.run(cmd, check=True)

    stream_bytes = temp_stream.read_bytes()
    try:
        temp_stream.unlink()
    except OSError:
        pass
    return stream_bytes

def create_evidence_disk(stream_bytes: bytes, output_path: Path):
    """
    Build a raw .dd forensic disk image containing:
    1. Hikvision Master Sector (Magic at 0x200)
    2. Wiped Index (simulating that the video index has been erased/deleted)
    3. The raw stream bytes in unallocated/slack sectors
    4. Surrounding noise/slack space
    """
    buf = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    # Master sector at 0x200
    buf += HIKV_MASTER_SECTOR_MAGIC + b"\x00" * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    
    # Unallocated noise & decoys (simulating deleted index table)
    buf += generate_decoys()
    buf += b"\x00" * 4096  # Wiped index block (zeroed out)
    buf += b"\xCC" * 8192  # Slack fill
    
    # Payload: the deleted video sitting in raw unallocated space
    buf += stream_bytes
    
    # Trailing slack and decoys
    buf += b"\xCC" * 8192
    buf += generate_decoys()
    buf += b"\x00" * 4096
    
    output_path.write_bytes(buf)

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/prepare_test_evidence.py <input_video> [output_image.dd]")
        sys.exit(1)

    input_video = Path(sys.argv[1]).resolve()
    if not input_video.is_file():
        print(f"Error: Input video not found at: {input_video}")
        sys.exit(1)

    output_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else input_video.parent / f"{input_video.stem}_forensic_evidence.dd"

    print(f"[*] Processing Input Ground Truth Video: {input_video.name} ({input_video.stat().st_size:,} bytes)")
    
    # Calculate SHA-256 of Ground Truth
    gt_hash = hashlib.sha256(input_video.read_bytes()).hexdigest()
    print(f"[*] Ground Truth SHA-256: {gt_hash}")
    
    print("[*] Extracting raw surveillance stream...")
    stream_bytes = extract_stream_bytes(input_video)
    print(f"[*] Extracted stream: {len(stream_bytes):,} bytes")

    print("[*] Generating forensic Hikvision disk image with deleted/unindexed stream...")
    create_evidence_disk(stream_bytes, output_path)

    dd_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    print(f"[+] Forensic Evidence Created: {output_path.name}")
    print(f"    - File Path: {output_path}")
    print(f"    - Size:      {output_path.stat().st_size:,} bytes")
    print(f"    - SHA-256:   {dd_hash}")
    print("\nNext steps in A.E.G.I.S (http://127.0.0.1:8000):")
    print(" 1. Ingest this .dd image into a new case.")
    print(" 2. Run 'Carve & Scan' to recover the deleted footage.")
    print(" 3. Go to 'Recordings -> Accuracy Against Ground Truth' and compare the carved clip against your original video!")

if __name__ == "__main__":
    main()
