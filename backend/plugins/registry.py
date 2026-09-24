"""
registry.py — the list of brand plugins and brand detection.

Kept separate from the web app so measurement/analysis code can detect a brand without
importing FastAPI or opening a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.plugins.cpplus import CPPlusPlugin
from backend.plugins.dahua import DahuaPlugin
from backend.plugins.godrej import GodrejPlugin
from backend.plugins.hikvision import HikvisionPlugin
from backend.plugins.honeywell import HoneywellPlugin
from backend.plugins.matrix import MatrixPlugin
from backend.plugins.tplink import TPLinkPlugin
from backend.plugins.uniview import UniviewPlugin
from backend.plugins.unknown import UnknownPlugin

if TYPE_CHECKING:
    from backend.acquisition import EvidenceImage

PLUGINS = [
    CPPlusPlugin(),
    DahuaPlugin(),
    HikvisionPlugin(),
    UniviewPlugin(),
    MatrixPlugin(),
    HoneywellPlugin(),
    TPLinkPlugin(),
    GodrejPlugin(),
]


def detect_brand(img: "EvidenceImage") -> tuple[str, str, float, Any]:
    """Run all plugins' detect() and return (brand, version, confidence, plugin)."""
    best_conf = 0.0
    best_plugin: Any = UnknownPlugin()
    for plugin in PLUGINS:
        try:
            conf = plugin.detect(img)
        except Exception:
            conf = 0.0
        if conf > best_conf:
            best_conf = conf
            best_plugin = plugin
    # display_name carries UI/report labels (e.g. "detection-only / unverified").
    return best_plugin.display_name, best_plugin.version_hint(), best_conf, best_plugin
