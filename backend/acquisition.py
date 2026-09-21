"""
acquisition.py — Safe, read-only disk image loading and hashing.

Rules (PRD §5.6.5, §FR-02, §FR-03, §FR-04):
  - v1 supports raw image FILES only (.dd, .img, .raw, .bin).
    Physical disk paths (\\.\PhysicalDriveN on Windows, /dev/sdX on Linux) are
    REJECTED with a clear error. The examiner must first create a .dd image using
    FTK Imager, dc3dd, or a hardware write blocker and dd.
  - The image is opened with mmap.ACCESS_READ (never writable).
  - SHA-256 and MD5 are computed in a single streaming pass (one read of the file).
  - The image is re-hashed at the end of every scan and compared with the before-hash.
  - No write is ever performed to the evidence file or its directory.

Windows note: mmap on Windows requires the file to be opened normally ('rb');
  ACCESS_READ maps the file read-only. Write-protection is enforced by the OS when
  the file is opened read-only. The examiner is responsible for hardware write-block
  before the image is created — see README §Safe acquisition.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

from backend.plugins.constants import HASH_CHUNK_BYTES


# ── Exceptions ────────────────────────────────────────────────────────────────

class AcquisitionError(Exception):
    """Raised when the image cannot be opened safely."""


# ── EvidenceImage ─────────────────────────────────────────────────────────────

class EvidenceImage:
    """
    Context manager that opens a disk image file in read-only mode.

    Usage:
        with EvidenceImage.open(path) as img:
            img.sha256_before  # computed on open
            mm = img.mm        # read-only mmap
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.size: int = 0
        self.sha256_before: str = ""
        self.md5_before: str = ""
        self.is_synthetic: bool = False  # set by caller from path/metadata
        self._file = None
        self.mm: Optional[mmap.mmap] = None

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "EvidenceImage":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if self.mm is not None:
            try:
                self.mm.close()
            except Exception:
                pass
            self.mm = None
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def open(
        cls,
        path: Path | str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> "EvidenceImage":
        """
        Open *path* as a read-only disk image.

        Args:
            path: Path to a raw image file (.dd / .img / .raw / .bin).
            progress_cb: Optional callback(bytes_done, total_bytes) called every
                         chunk while computing the opening hash.

        Raises:
            AcquisitionError: if the path looks like a physical disk, is not a
                              regular file, or cannot be opened.
        """
        path = Path(path)
        _reject_if_physical_disk(path)
        _reject_if_not_regular_file(path)

        img = cls(path)
        img._file = open(path, "rb")
        try:
            img.mm = mmap.mmap(img._file.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception as exc:
            img._file.close()
            raise AcquisitionError(f"Cannot memory-map {path}: {exc}") from exc

        img.size = img.mm.size()
        img.sha256_before, img.md5_before = _hash_mmap(img.mm, progress_cb)
        img.mm.seek(0)
        return img

    # ── Re-verification ───────────────────────────────────────────────────────

    def verify_unchanged(
        self,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """
        Re-hash the image and return True iff SHA-256 matches sha256_before.
        This is KAT-08: confirm the tool never wrote to the evidence.
        """
        if self.mm is None:
            raise AcquisitionError("Image is closed")
        self.mm.seek(0)
        sha256_after, _ = _hash_mmap(self.mm, progress_cb)
        self.mm.seek(0)
        return sha256_after == self.sha256_before


# ── Helper functions ──────────────────────────────────────────────────────────

def _reject_if_physical_disk(path: Path) -> None:
    """
    Raise AcquisitionError if path looks like a physical disk device.
    v1 supports image FILES only.
    """
    s = str(path)
    # Windows: \\.\PhysicalDriveN  or  \\?\Device\...
    if re.match(r"^\\\\[.?]\\", s):
        raise AcquisitionError(
            f"Physical disk paths are not supported in v1.\n"
            f"  Path: {path}\n"
            f"  Create a raw image file first using FTK Imager, dc3dd, or dd:\n"
            f"    Linux:   sudo dc3dd if=/dev/sdX of=evidence.dd hash=sha256\n"
            f"    Windows: Use FTK Imager → File → Create Disk Image → Raw (dd)\n"
            f"  Always use a hardware write blocker before connecting the disk."
        )
    # Linux/macOS: /dev/sdX or /dev/nvmeXnY
    if re.match(r"^/dev/", s):
        raise AcquisitionError(
            f"Physical disk device paths are not supported in v1.\n"
            f"  Path: {path}\n"
            f"  Create a raw image first:\n"
            f"    sudo blockdev --setro /dev/sdX   # write-protect\n"
            f"    sudo dc3dd if=/dev/sdX of=evidence.dd hash=sha256\n"
            f"  Never accept an OS prompt to initialise or format the disk."
        )


def _reject_if_not_regular_file(path: Path) -> None:
    if not path.exists():
        raise AcquisitionError(f"File not found: {path}")
    if not path.is_file():
        raise AcquisitionError(f"Not a regular file: {path}")
    if path.stat().st_size == 0:
        raise AcquisitionError(f"File is empty: {path}")


def _hash_mmap(
    mm: mmap.mmap,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[str, str]:
    """
    Stream-hash an open mmap in HASH_CHUNK_BYTES chunks.
    Returns (sha256_hex, md5_hex).
    A single pass is used — reading the image a second time for hashing is avoided
    because large drives can take many minutes to read (PRD §4.3 / 2013 paper).
    """
    sha256 = hashlib.sha256()
    md5    = hashlib.md5()
    total  = mm.size()
    done   = 0
    mm.seek(0)

    while True:
        chunk = mm.read(HASH_CHUNK_BYTES)
        if not chunk:
            break
        sha256.update(chunk)
        md5.update(chunk)
        done += len(chunk)
        if progress_cb:
            try:
                progress_cb(done, total)
            except Exception:
                pass  # progress errors must never abort acquisition

    return sha256.hexdigest(), md5.hexdigest()


def load_disk_image(path: Path | str) -> tuple[mmap.mmap, str, str, int]:
    """Convenience loader returning (mmap_obj, sha256_hash, md5_hash, size_bytes)."""
    img = EvidenceImage.open(path)
    return img.mm, img.sha256_before, img.md5_before, img.size


def verify_disk_image_integrity(path: Path | str, expected_sha256: str) -> tuple[bool, str]:
    """Re-verify disk image SHA-256 against expected hash."""
    img = EvidenceImage.open(path)
    current_sha256 = img.sha256_before
    img.close()
    return current_sha256 == expected_sha256, current_sha256

