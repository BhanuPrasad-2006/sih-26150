"""
tplink.py — TP-Link (VIGI / Tapo) DVR/NVR brand plugin.

DETECTION-ONLY STUB / UNVERIFIED
================================
This plugin does **not** parse TP-Link disks. No reliable public
documentation of a TP-Link DVR/NVR on-disk file-system or frame container
was found (unlike Dahua DHAV or Hikvision's master-sector signature).
See docs/oem_comparison.md.

detect() may look for unverified vendor ASCII strings. A hit is reported
as low confidence only — never a verified brand match. Absence of those
strings returns 0.0.

carve() and format parsing are not implemented.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

log = logging.getLogger(__name__)

# Unverified ASCII probes only — not a documented file-system magic or offset.
# Public forensic literature does not establish a TP-Link DVR/NVR disk layout.
_UNVERIFIED_ASCII_MARKERS = (b"TP-LINK", b"TPLINK", b"VIGI")
_DETECT_SCAN_BYTES = 32 * 1024 * 1024
_STRING_HIT_CONFIDENCE = 0.15  # honest low score; never a verified brand match


class TPLinkPlugin(BrandPlugin):
    """Detection-only / unverified stub. Does not recover video."""

    name = "tplink"
    display_name = "TP-Link (detection-only / unverified)"

    def detect(self, img: "EvidenceImage") -> float:
        """
        Scan a prefix of the image for unverified ASCII markers.

        Returns 0.15 if a marker is found, otherwise 0.0.
        Never claims a verified format match.
        """
        try:
            mm = img.mm
            limit = min(img.size, _DETECT_SCAN_BYTES)
            for marker in _UNVERIFIED_ASCII_MARKERS:
                if mm.find(marker, 0, limit) != -1:
                    log.info(
                        "TP-Link detect(): unverified ASCII marker %r found; "
                        "reporting low confidence (detection-only stub).",
                        marker,
                    )
                    return _STRING_HIT_CONFIDENCE
            return 0.0
        except Exception as exc:
            log.debug("TP-Link detect() error: %s", exc)
            return 0.0

    def version_hint(self) -> str:
        return (
            "TP-Link — detection-only / unverified stub. "
            "No public on-disk format is documented in this project; "
            "carving and index parsing are not implemented."
        )

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        note = (
            "TP-Link index parsing is not implemented (detection-only / unverified stub)."
        )
        log.info(note)
        return [], note

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        note = "TP-Link format parsing not yet implemented — detection only."
        log.info(note)
        return [], note
