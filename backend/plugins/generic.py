"""
generic.py — Generic standards-based stream carving for unidentified recorders.

Used as a fallback when no brand plugin identifies a disk. It never claims a
brand: detect() always returns 0.0. It exists so recorders whose formats are
undocumented (e.g. Uniview, TP-Link, Godrej, Matrix — no public research found)
can still yield evidence WHEN they store standard MPEG-PS or H.264 Annex B
streams, using only the public standards in stream_carver.py.

Limits: no timestamps, no camera numbers, no index. Results are UNCERTAIN until
FFmpeg decodes the export (then PARTIAL). Streams inside proprietary containers
(private headers between every NAL, encryption, H.265-only, etc.) will not be found.
"""

from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

from backend.models import RawFrame
from backend.plugins.base import BrandPlugin
from backend.plugins.stream_carver import carve_standard_streams

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage


class GenericStreamPlugin(BrandPlugin):
    name = "generic"
    display_name = "Unidentified recorder (generic stream carving)"

    def detect(self, img: "EvidenceImage") -> float:
        return 0.0

    def version_hint(self) -> str:
        return "Brand not identified; standards-based MPEG-PS / H.264 stream carving only"

    def list_recordings(self, img: "EvidenceImage") -> tuple[list[RawFrame], str]:
        return [], "No recorder-specific index is used for unidentified recorders."

    def carve(
        self,
        img: "EvidenceImage",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[RawFrame], str]:
        return carve_standard_streams(img, "generic", progress_cb)
