"""
model_integrity.py — Refuse to run a shipped ONNX model whose bytes differ from the pinned SHA-256.

The three models are third-party files loaded into a native inference engine; a swapped or corrupted file
would run silently. The pinned values are the SHA-256 of the files as committed to this repository
(sourced from the OpenCV model zoo); they are a tamper check for the copy on disk, not proof about upstream.

A model that is not in the table (for example one supplied through OBJECT_MODEL_PATH) is allowed but reported
as unverified. Set SIH_SKIP_MODEL_VERIFY=1 to bypass (development only).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PINNED_SHA256 = {
    "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "face_recognition_sface_2021dec.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    "object_detection_yolox_2022nov.onnx": "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
}

_cache: dict[tuple[str, int, int], tuple[bool, str]] = {}


def verify_model(path: str | Path) -> tuple[bool, str]:
    """Return (ok, message). ok is False only when a pinned model's hash does not match."""
    if os.environ.get("SIH_SKIP_MODEL_VERIFY", "") == "1":
        return True, "model verification skipped (SIH_SKIP_MODEL_VERIFY=1)"
    p = Path(path)
    expected = PINNED_SHA256.get(p.name)
    if expected is None:
        log.warning("Model %s is not in the pinned list; running unverified.", p.name)
        return True, f"{p.name}: not a pinned model, unverified"
    try:
        st = p.stat()
    except OSError as exc:
        return False, f"{p.name}: cannot read model ({exc})"
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if key in _cache:
        return _cache[key]
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    ok = h.hexdigest() == expected
    result = (ok, f"{p.name}: integrity OK" if ok else
              f"{p.name}: SHA-256 does not match the pinned value (file changed or corrupted); refusing to load it")
    _cache[key] = result
    return result
