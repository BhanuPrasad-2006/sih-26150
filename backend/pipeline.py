"""
pipeline.py — The recovery pipeline without the web app or a database: detect → index → carve → reconstruct.

Mirrors the steps of main._run_scan (which additionally stores results, writes audit entries and reports progress
over SSE). It exists so headless tools (the validation kit) run exactly the same decisions as the application; a test
asserts the two agree on the same image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.acquisition import EvidenceImage
from backend.models import RawFrame, Segment
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE
from backend.plugins.generic import GenericStreamPlugin
from backend.plugins.registry import detect_brand
from backend.plugins.unknown import UnknownPlugin
from backend.reconstructor import label_all


@dataclass
class RecoveryResult:
    brand: str
    brand_version: str
    confidence: float
    plugin_name: str
    plugin_display_name: str
    generic_fallback: bool
    index_note: str
    carve_note: str
    index_frames: int
    carved_frames: int
    segments: list[Segment] = field(default_factory=list)
    unidentified: bool = False           # generic fallback found nothing at all


def recover(
    img: EvidenceImage,
    evidence_id: str = "headless",
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> RecoveryResult:
    brand, version, confidence, plugin = detect_brand(img)
    generic = False
    if confidence < MIN_PLUGIN_CONFIDENCE:
        generic = True
        hinted = plugin if (confidence > 0 and not isinstance(plugin, UnknownPlugin)) else None
        plugin = GenericStreamPlugin()
        brand = (f"{hinted.display_name} — generic stream carving" if hinted else plugin.display_name)
        version = plugin.version_hint()

    index_frames, index_note = plugin.list_recordings(img)
    carved_frames, carve_note = plugin.carve(img, progress_cb)

    if generic and not carved_frames:
        return RecoveryResult(brand, version, confidence, plugin.name, plugin.display_name, True, index_note,
                              carve_note, len(index_frames), 0, [], unidentified=True)

    segments = label_all(index_frames + carved_frames, evidence_id)
    return RecoveryResult(brand, version, confidence, plugin.name, plugin.display_name, generic, index_note,
                          carve_note, len(index_frames), len(carved_frames), segments)
