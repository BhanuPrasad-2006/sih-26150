"""
base.py — Abstract BrandPlugin interface.

Every brand plugin must subclass BrandPlugin and implement detect(), list_recordings() and carve().
read_logs() is optional (returns [] by default).

All methods must:
  - Never write to the mmap or the evidence path.
  - Catch and log every frame-level error instead of propagating (bad frames are skipped).
  - Return lists, never raise, unless there is a fatal setup error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from backend.models import LogEvent, RawFrame, Segment

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage


class BrandPlugin(ABC):
    """
    Abstract base class for all brand plugins.

    Attributes:
        name (str): Machine-readable brand identifier, e.g. "dahua" or "hikvision".
        display_name (str): Human-readable brand name for UI and reports.
    """

    name: str = "unknown"
    display_name: str = "Unknown"

    @abstractmethod
    def detect(self, img: "EvidenceImage") -> float:
        """
        Examine the disk image and return a confidence score 0.0–1.0
        that this plugin can parse the image.

        1.0 = strong match (e.g. magic bytes found at expected offset)
        0.0 = definitely not this brand
        0.5 = some evidence but ambiguous

        Must not modify the mmap position permanently.
        Must not raise — return 0.0 on any error.
        """
        ...

    @abstractmethod
    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        """
        Read the brand's file-system index and return normal (not-deleted) recordings.

        Returns:
            (frames, note) where:
              - frames is a (possibly empty) list of RawFrame objects
              - note is a human-readable status string, e.g. "read 47 frames from index"
                or "index parsing not yet implemented — use carving"

        Must not raise — return ([], error_note) on failure.
        """
        ...

    @abstractmethod
    def carve(
        self,
        img: "EvidenceImage",
        progress_cb=None,
    ) -> tuple[list[RawFrame], str]:
        """
        Scan the entire disk image for frame markers (carving).
        Used to find deleted or lost video not listed in the index.

        Args:
            img: The open EvidenceImage.
            progress_cb: Optional callable(bytes_scanned, total_bytes) for progress updates.

        Returns:
            (frames, note) where note describes what was done.

        Must not raise — return ([], error_note) on failure.
        """
        ...

    def read_logs(self, img: "EvidenceImage") -> list[LogEvent]:
        """
        Optional: extract log events (formatting, recording changes, logins).
        Override in plugins that support it.
        Default: return [].
        """
        return []

    def version_hint(self) -> str:
        """
        Return a string describing the detected version / variant if known.
        Called after detect(). Override if version detection is possible.
        """
        return ""
