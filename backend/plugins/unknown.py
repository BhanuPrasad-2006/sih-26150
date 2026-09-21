"""
unknown.py — Fallback plugin that detects standard file systems and encryption.

This plugin is run when no brand plugin reaches MIN_PLUGIN_CONFIDENCE.
It does not attempt to read video — it only tells the user WHY the disk
was not recognised and advises on next steps.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import (
    BITLOCKER_MAGIC,
    BITLOCKER_MAGIC_OFFSET,
    EXFAT_MAGIC,
    EXFAT_MAGIC_OFFSET,
    EXT4_MAGIC,
    EXT4_SUPERBLOCK_OFFSET,
    NTFS_MAGIC,
    NTFS_MAGIC_OFFSET,
)

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)


class UnknownPlugin(BrandPlugin):
    """
    Identifies foreign / encrypted / unsupported disk images.
    Always returns low confidence so the scanner knows this is a fallback.
    """

    name = "unknown"
    display_name = "Unknown / Unsupported"

    def __init__(self) -> None:
        self._description: str = "No recognised DVR/NVR signature found."

    def detect(self, img: "EvidenceImage") -> float:
        """
        Scan for standard file-system and encryption magic bytes.
        Returns 0.05 (never high enough to trigger scanning).
        Sets self._description so the caller can show a useful warning.
        """
        try:
            mm = img.mm
            size = img.size

            # BitLocker (FVE)
            if size > BITLOCKER_MAGIC_OFFSET + 16:
                if mm[BITLOCKER_MAGIC_OFFSET: BITLOCKER_MAGIC_OFFSET + 8] == BITLOCKER_MAGIC:
                    self._description = (
                        "BitLocker-encrypted volume detected. "
                        "This tool does not break encryption. "
                        "Decrypt the volume first using the recovery key, "
                        "then re-image and load the plaintext image."
                    )
                    return 0.05

            # NTFS
            if size > NTFS_MAGIC_OFFSET + 8:
                if mm[NTFS_MAGIC_OFFSET: NTFS_MAGIC_OFFSET + 8] == NTFS_MAGIC:
                    self._description = (
                        "NTFS file system detected. "
                        "This does not appear to be a proprietary DVR/NVR disk. "
                        "Check that you loaded the correct image."
                    )
                    return 0.05

            # exFAT
            if size > EXFAT_MAGIC_OFFSET + 8:
                if mm[EXFAT_MAGIC_OFFSET: EXFAT_MAGIC_OFFSET + 8] == EXFAT_MAGIC:
                    self._description = (
                        "exFAT file system detected. "
                        "This does not appear to be a proprietary DVR/NVR disk."
                    )
                    return 0.05

            # ext4
            if size > EXT4_SUPERBLOCK_OFFSET + 2:
                if mm[EXT4_SUPERBLOCK_OFFSET: EXT4_SUPERBLOCK_OFFSET + 2] == EXT4_MAGIC:
                    self._description = (
                        "ext4 (Linux) file system detected. "
                        "Some Dahua NVR systems store video on XFS or ext4 — "
                        "in this case the Dahua plugin may still find DHAV frames "
                        "by carving. Run the Dahua plugin manually if needed."
                    )
                    return 0.05

        except Exception as exc:
            log.debug("UnknownPlugin.detect() error: %s", exc)

        return 0.05

    def description(self) -> str:
        return self._description

    def version_hint(self) -> str:
        return self._description

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        return [], "Unknown disk type — cannot list recordings."

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        return [], "Unknown disk type — carving not attempted."
