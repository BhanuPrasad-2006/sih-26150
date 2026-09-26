"""
certificate_meta.py — examiner-entered details for the Section 63(4) certificate pages of the PDF report.

The tool cannot know who seized a device, which police station or FIR the case belongs to, or the recorder's
serial number. The examiner types them in; they are stored per case and printed in the report exactly as entered,
marked "as entered by the examiner (not verified by the tool)". Fields left blank are listed as not provided.

Storage: one JSON value per case in the key/value table the database layer already has for both SQLite and
Postgres (key ``case_meta:<case_id>:certificate``), so no schema change is needed.
"""

from __future__ import annotations

import json
import re
from typing import Optional

MAX_FIELD_LENGTH = 200

# (key, label used in the report and the form)
FIELDS: list[tuple[str, str]] = [
    ("police_station",      "Police station / agency"),
    ("fir_number",          "FIR / crime reference number"),
    ("seizure_officer",     "Seizure officer name"),
    ("seizure_officer_rank", "Seizure officer rank"),
    ("device_make_model",   "Recorder make and model"),
    ("device_serial",       "Recorder serial number"),
]
FIELD_KEYS = [k for k, _ in FIELDS]
LABELS = dict(FIELDS)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _key(case_id: str) -> str:
    return f"case_meta:{case_id}:certificate"


def clean(data: Optional[dict]) -> dict[str, str]:
    """Keep only known fields, as trimmed single-line strings of at most MAX_FIELD_LENGTH characters."""
    out: dict[str, str] = {}
    for key in FIELD_KEYS:
        value = (data or {}).get(key)
        if value is None:
            out[key] = ""
            continue
        text = _CONTROL.sub(" ", str(value)).strip()
        out[key] = re.sub(r"\s+", " ", text)[:MAX_FIELD_LENGTH]
    return out


def load(db, case_id: str) -> dict[str, str]:
    raw = db.get_auth_value(_key(case_id))
    if not raw:
        return clean({})
    try:
        return clean(json.loads(raw))
    except (ValueError, TypeError):
        return clean({})


def save(db, case_id: str, data: dict) -> dict[str, str]:
    cleaned = clean(data)
    db.set_auth_value(_key(case_id), json.dumps(cleaned, ensure_ascii=False))
    return cleaned


def missing_labels(details: Optional[dict]) -> list[str]:
    """Labels of the fields the examiner left blank (all of them when nothing was entered)."""
    cleaned = clean(details)
    return [LABELS[k] for k in FIELD_KEYS if not cleaned[k]]
