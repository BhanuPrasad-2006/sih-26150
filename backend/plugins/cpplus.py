"""
cpplus.py — CP Plus (Dahua-compatible detection — unverified) brand plugin.

DETECTION STUB / DAHUA COMPATIBILITY (UNVERIFIED)
=================================================
CP Plus video surveillance systems (Orange, Indigo, Cosmic, Coral series DVRs/NVRs)
distributed in India by Aditya Infotech are frequently OEM-derived from Dahua
platforms running Dahua-compatible firmware and container formats.

When CP Plus identification strings/markers are detected on disk along with
valid DHAV frame structures:
  - The brand is identified as:
    "CP Plus (Dahua-compatible detection — unverified)"
  - Carving and extraction route through the Dahua plugin (DHAV parser).
  - It is NEVER claimed as verified or native CP Plus filesystem parsing.

If CP Plus markers are found without DHAV frame structures, detect() reports
low confidence (0.20, below threshold), indicating an unverified or unsupported
CP Plus variant.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.constants import CPPLUS_IDENTIFYING_MARKERS
from backend.plugins.dahua import DahuaPlugin

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

_DETECT_SCAN_BYTES = 32 * 1024 * 1024  # 32 MB
_STRING_ONLY_CONFIDENCE = 0.20  # CP Plus marker found but no DHAV frames
_COMPATIBLE_CONFIDENCE = 0.95   # CP Plus marker found AND valid DHAV frames


class CPPlusPlugin(BrandPlugin):
    """
    CP Plus detection stub that routes carving through the Dahua DHAV plugin.
    Must always be displayed as 'CP Plus (Dahua-compatible detection — unverified)'.
    """

    name = "cpplus"
    display_name = "CP Plus (Dahua-compatible detection — unverified)"

    def __init__(self) -> None:
        self._dahua = DahuaPlugin()
        self._has_dhav = False
        self._has_cpplus_marker = False

    def detect(self, img: "EvidenceImage") -> float:
        """
        Scan prefix of disk image for CP Plus identifying strings and DHAV frames.

        Returns:
          1.0 if CP Plus markers AND DHAV frames are found (routes to Dahua).
          0.20 if CP Plus markers are found WITHOUT DHAV frames (unsupported/unverified).
          0.00 if no CP Plus markers are found.
        """
        try:
            mm = img.mm
            limit = min(img.size, _DETECT_SCAN_BYTES)
            self._has_cpplus_marker = False

            for marker in CPPLUS_IDENTIFYING_MARKERS:
                if mm.find(marker, 0, limit) != -1:
                    log.info(
                        "CP Plus detect(): identifying marker %r found",
                        marker,
                    )
                    self._has_cpplus_marker = True
                    break

            if not self._has_cpplus_marker:
                return 0.0

            # Marker found. Now check if Dahua DHAV frames exist
            dahua_conf = self._dahua.detect(img)
            if dahua_conf >= 0.5:
                self._has_dhav = True
                log.info(
                    "CP Plus detect(): DHAV frames also confirmed (conf=%.2f); "
                    "identifying as CP Plus (Dahua-compatible detection — unverified)",
                    dahua_conf,
                )
                return max(_COMPATIBLE_CONFIDENCE, dahua_conf)

            self._has_dhav = False
            log.info(
                "CP Plus detect(): marker found but no DHAV frames; "
                "reporting low confidence (unverified stub)"
            )
            return _STRING_ONLY_CONFIDENCE
        except Exception as exc:
            log.debug("CPPlus detect() error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        if self._has_cpplus_marker and self._has_dhav:
            return (
                "CP Plus (Dahua-compatible detection — unverified) — "
                "DHAV frame structure detected; carved via Dahua DHAV engine."
            )
        return (
            "CP Plus (Dahua-compatible detection — unverified) — "
            "Identification marker detected without verified DHAV frames. "
            "Native CP Plus filesystem/container parsing is not implemented."
        )

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        recs, note = self._dahua.list_recordings(img)
        cpplus_note = f"CP Plus (unverified): {note}"
        return recs, cpplus_note

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        """
        Route carving through the Dahua plugin.
        """
        log.info("CP Plus carve(): Routing to Dahua DHAV carving engine...")
        frames, note = self._dahua.carve(img, progress_cb)
        cpplus_note = f"Carved via Dahua plugin (CP Plus Dahua-compatible — unverified): {note}"
        return frames, cpplus_note
