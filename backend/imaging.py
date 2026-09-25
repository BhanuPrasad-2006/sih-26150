"""
imaging.py — Read-only forensic imaging of a drive (or a file) into a raw .dd image.

This is the "acquisition" step that acquisition.py deliberately does not do:
acquisition.py opens an image that already exists; this module CREATES one.

What it does
  - Opens the source read-only and never writes to it.
  - Copies it sector-consistently into <dest> (raw, bit-for-bit), hashing the
    exact bytes written (SHA-256 + MD5) in the same pass.
  - Unreadable sectors are retried one sector at a time; sectors that still
    fail are zero-filled, listed with their byte offsets, and reported. The
    image is therefore NOT byte-identical to the source in those ranges and
    the report says so (same behaviour as dc3dd/dd conv=noerror,sync).
  - Re-reads the finished image and checks its hash equals the streamed hash
    (proves what is on disk is what was hashed).
  - Optionally re-reads the SOURCE and checks it hashes the same (proves the
    source did not change during imaging; not possible if bad sectors were hit).
  - Writes <dest>.acquisition.json beside the image.

What it CANNOT do — the examiner must ensure these
  - Software cannot guarantee that the operating system did not write to the
    disk. Use a hardware write blocker (or a read-only OS mount) and state so:
    the report only records the examiner's attestation.
  - It has not been run on a real physical disk in development; the device
    code path (raw device open, size discovery) is verified only on ordinary
    files. Validate on a scratch disk before relying on it.
  - It does not image an in-use system disk reliably and refuses to write the
    image onto the source device.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from backend.acquisition import AcquisitionError

TOOL_NAME = "SIH DVR/NVR Forensic Tool imaging module"
CHUNK_BYTES = 1024 * 1024                 # multiple of 512 and 4096 (raw devices need aligned reads)
SECTOR_BYTES = 512
MAX_RECORDED_BAD_RANGES = 10_000          # keep the report bounded on a dying drive

_DEVICE_RE = re.compile(r"^(\\\\[.?]\\|/dev/)")


def is_device_path(path: str | Path) -> bool:
    return bool(_DEVICE_RE.match(str(path)))


@dataclass
class ImagingReport:
    source: str
    dest: str
    source_is_device: bool
    bytes_written: int
    sha256: str
    md5: str
    started_utc: str
    finished_utc: str
    duration_seconds: float
    bad_ranges: list[tuple[int, int]] = field(default_factory=list)   # (byte_offset, length), zero-filled
    bad_ranges_truncated: bool = False
    dest_hash_verified: bool = False
    source_rehash_verified: Optional[bool] = None    # None = not requested / not possible
    stopped_early: bool = False                      # max_bytes reached before source end
    write_blocker_attested: bool = False
    tool: str = TOOL_NAME
    platform: str = field(default_factory=platform.platform)
    notes: list[str] = field(default_factory=list)

    @property
    def bad_bytes(self) -> int:
        return sum(length for _, length in self.bad_ranges)

    @property
    def is_bit_exact(self) -> bool:
        """True only when every sector was read and the image verified."""
        return self.dest_hash_verified and not self.bad_ranges and not self.bad_ranges_truncated

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bad_bytes"] = self.bad_bytes
        d["is_bit_exact"] = self.is_bit_exact
        return d


def _sha_md5_file(path: Path, progress_cb: Optional[Callable[[int, int], None]] = None) -> tuple[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)   # MD5: reported for forensic practice only
    total = path.stat().st_size
    done = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            sha.update(chunk)
            md5.update(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total)
    return sha.hexdigest(), md5.hexdigest()


def _device_size(f, path: str) -> Optional[int]:
    """Best-effort total size of an open raw device; None if it can't be found."""
    try:
        size = f.seek(0, os.SEEK_END)
        f.seek(0)
        if size and size > 0:
            return int(size)
    except OSError:
        pass
    try:
        f.seek(0)
    except OSError:
        pass
    return None


def _read_chunk(f, offset: int, want: int, report: ImagingReport) -> bytes:
    """
    Read up to `want` bytes at `offset`. On an I/O error retry sector by sector;
    sectors that still fail are zero-filled and recorded.
    """
    try:
        f.seek(offset)
        return f.read(want)
    except OSError:
        pass

    out = bytearray()
    for pos in range(0, want, SECTOR_BYTES):
        n = min(SECTOR_BYTES, want - pos)
        try:
            f.seek(offset + pos)
            piece = f.read(n)
        except OSError:
            piece = b""
            if len(report.bad_ranges) < MAX_RECORDED_BAD_RANGES:
                start = offset + pos
                if report.bad_ranges and sum(report.bad_ranges[-1]) == start:
                    last = report.bad_ranges[-1]
                    report.bad_ranges[-1] = (last[0], last[1] + n)
                else:
                    report.bad_ranges.append((start, n))
            else:
                report.bad_ranges_truncated = True
            out += b"\x00" * n
            continue
        if not piece:                                        # clean EOF part-way through the chunk
            break
        out += piece
        if len(piece) < n:
            break
    return bytes(out)


def acquire_image(
    source: str | Path,
    dest: str | Path,
    *,
    write_blocker_attested: bool,
    max_bytes: Optional[int] = None,
    verify_source: bool = False,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    _opener: Callable = open,                 # test seam: inject a source that raises I/O errors
) -> ImagingReport:
    """
    Image `source` (a file or a raw device path) into the new file `dest`.

    Refuses when: the attestation is missing, dest exists, dest is the source,
    dest is a device path, or the source cannot be opened read-only.
    """
    if not write_blocker_attested:
        raise AcquisitionError(
            "Write-blocker attestation is required. Connect the source through a hardware "
            "write blocker (or a read-only mount) and confirm it before imaging."
        )
    src, dst = Path(source), Path(dest)
    if is_device_path(dst):
        raise AcquisitionError("The destination must be a regular file, never a device path.")
    if dst.exists():
        raise AcquisitionError(f"Destination already exists (refusing to overwrite evidence): {dst}")
    src_is_device = is_device_path(src)
    if not src_is_device:
        if not src.exists():
            raise AcquisitionError(f"Source not found: {src}")
        if not src.is_file():
            raise AcquisitionError(f"Source is not a regular file or device: {src}")
    if dst.parent and not dst.parent.exists():
        raise AcquisitionError(f"Destination folder does not exist: {dst.parent}")

    try:
        f = _opener(src, "rb", buffering=0)
    except PermissionError as exc:
        raise AcquisitionError(
            f"Permission denied opening {src} read-only. Raw devices usually require "
            f"administrator/root rights. ({exc})"
        ) from exc
    except OSError as exc:
        raise AcquisitionError(f"Cannot open source {src}: {exc}") from exc

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    report = ImagingReport(
        source=str(src), dest=str(dst), source_is_device=src_is_device, bytes_written=0,
        sha256="", md5="", started_utc=started.isoformat(), finished_utc="", duration_seconds=0.0,
        write_blocker_attested=True,
    )
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)   # MD5: reported for forensic practice only

    try:
        total = _device_size(f, str(src)) if src_is_device else src.stat().st_size
        if max_bytes is not None and total is not None:
            limit = min(total, max_bytes)
        elif max_bytes is not None:
            limit = max_bytes
        else:
            limit = total
        if src_is_device and total is None:
            report.notes.append("Device size could not be read; imaged until the device reported end of data.")

        offset = 0
        try:
            with open(dst, "xb") as out:                       # 'x': fail rather than overwrite
                while limit is None or offset < limit:
                    want = CHUNK_BYTES if limit is None else min(CHUNK_BYTES, limit - offset)
                    data = _read_chunk(f, offset, want, report)
                    if not data:
                        break
                    out.write(data)
                    sha.update(data)
                    md5.update(data)
                    offset += len(data)
                    if progress_cb:
                        progress_cb(offset, limit)
                    if len(data) < want:
                        break
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            # A partial image is not evidence; remove it instead of leaving a half file behind.
            try:
                dst.unlink()
            except OSError:
                pass
            raise
        report.bytes_written = offset
        report.stopped_early = bool(max_bytes is not None and total is not None and offset < total)
        if total is not None and not report.stopped_early and offset < total:
            report.notes.append(f"Source reported {total} bytes but only {offset} could be read.")
    finally:
        f.close()

    report.sha256, report.md5 = sha.hexdigest(), md5.hexdigest()

    # Prove the file on disk is what was hashed while reading.
    disk_sha, disk_md5 = _sha_md5_file(dst)
    report.dest_hash_verified = (disk_sha == report.sha256 and disk_md5 == report.md5)
    if not report.dest_hash_verified:
        report.notes.append("VERIFICATION FAILED: the written image does not match the streamed hash.")

    if verify_source:
        if report.bad_ranges:
            report.notes.append("Source re-hash skipped: unreadable sectors were zero-filled.")
        elif src_is_device or src.is_file():
            try:
                again = hashlib.sha256()
                remaining = report.bytes_written
                with open(src, "rb", buffering=0) as g:
                    while remaining > 0:
                        chunk = g.read(min(CHUNK_BYTES, remaining))
                        if not chunk:
                            break
                        again.update(chunk)
                        remaining -= len(chunk)
                report.source_rehash_verified = (remaining == 0 and again.hexdigest() == report.sha256)
            except OSError as exc:
                report.notes.append(f"Source re-hash could not be completed: {exc}")

    if report.bad_ranges:
        report.notes.append(
            f"{len(report.bad_ranges)} unreadable range(s), {report.bad_bytes} byte(s) zero-filled. "
            f"The image is not bit-exact in those ranges."
        )

    report.finished_utc = datetime.now(timezone.utc).isoformat()
    report.duration_seconds = round(time.monotonic() - t0, 3)
    Path(str(dst) + ".acquisition.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


# ── Listing local drives so the examiner can pick one ─────────────────────────

def list_local_drives() -> list[dict]:
    """
    Read-only inventory of physical drives on THIS machine (model, size, path).
    Returns [] where it can't be determined. Never opens the drives themselves.
    """
    system = platform.system()
    try:
        if system == "Windows":
            ps = ("Get-CimInstance Win32_DiskDrive | Select-Object DeviceID,Model,Size,InterfaceType,"
                  "MediaType | ConvertTo-Json -Compress")
            raw = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
            data = json.loads(raw) if raw else []
            if isinstance(data, dict):
                data = [data]
            return [{"path": d["DeviceID"], "model": d.get("Model"), "size_bytes": d.get("Size"),
                     "interface": d.get("InterfaceType"), "media": d.get("MediaType")} for d in data]
        if system == "Linux":
            raw = subprocess.run(["lsblk", "-J", "-b", "-d", "-o", "NAME,SIZE,MODEL,RO,TRAN,TYPE"],
                                 capture_output=True, text=True, timeout=20).stdout
            devs = json.loads(raw).get("blockdevices", [])
            return [{"path": f"/dev/{d['name']}", "model": d.get("model"), "size_bytes": int(d["size"]),
                     "interface": d.get("tran"), "media": "read-only" if d.get("ro") else None}
                    for d in devs if d.get("type") == "disk"]
    except Exception:
        return []
    return []
