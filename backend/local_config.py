"""
local_config.py — the first-run wizard's saved choices (data folder, terms accepted).

This is deliberately NOT part of the case database: it is per-installation, per-machine
configuration that must be readable before any database connection is even chosen (the case
folder location and the database itself are configured independently). It lives in a small JSON
file in the user's home directory, the same convention as ~/.aws, ~/.docker, etc.

FORENSIC_CASE_DIR (an explicit environment variable) always wins over this file — this keeps
Docker/server deployments, which set that variable directly, behaving exactly as before.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("local_config")

# Bumped whenever the terms shown in the first-run wizard change materially — a saved acceptance
# of an older version does not count, and the wizard is shown again.
TERMS_VERSION = "1.0"

CONFIG_DIR = Path(os.environ.get("SIH_CONFIG_DIR", "")) if os.environ.get("SIH_CONFIG_DIR") else Path.home() / ".sih_forensic_tool"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Best-effort read; a missing or corrupt file is just treated as first run."""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_first_run_complete() -> bool:
    cfg = load_config()
    return bool(cfg.get("case_dir")) and cfg.get("terms_accepted_version") == TERMS_VERSION


def configured_case_dir() -> Optional[str]:
    """The case folder chosen in the wizard, if any and if it still exists."""
    cfg = load_config()
    case_dir = cfg.get("case_dir")
    if case_dir and Path(case_dir).is_dir():
        return case_dir
    return None


def complete_first_run(case_dir: str) -> None:
    """Create the chosen folder if needed and record that the current terms were accepted."""
    path = Path(case_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    # Fail loudly here (not caught) if the folder truly cannot be used — the caller turns any
    # exception into a clear 400 for the wizard to show, rather than silently accepting a bad path.
    probe = path / ".sih_write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()

    cfg = load_config()
    cfg["case_dir"] = str(path)
    cfg["terms_accepted_version"] = TERMS_VERSION
    save_config(cfg)
    log.info("First-run setup complete: case_dir=%s terms_version=%s", path, TERMS_VERSION)


def _app_root() -> Path:
    # Inside a PyInstaller bundle, __file__ is not the source tree — sys._MEIPASS is the
    # extracted bundle root instead, and the VERSION file is bundled there as data (see the
    # .spec file's datas=[('VERSION', '.')]).
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


_FALLBACK_VERSION = "0.0.0-unknown"


def get_version() -> str:
    """The app's version, read from the VERSION file at the repo root. A single source of truth
    used for the FastAPI app version, the in-app display, and the update-check comparison."""
    try:
        return (_app_root() / "VERSION").read_text(encoding="utf-8").strip() or _FALLBACK_VERSION
    except Exception:
        return _FALLBACK_VERSION


def default_case_dir_suggestion() -> str:
    """What to pre-fill the wizard's folder field with, before the user changes it."""
    env = os.environ.get("FORENSIC_CASE_DIR", "")
    if env:
        return env
    if os.name == "nt":
        return "C:/sih_cases"
    return str(Path.home() / "sih_cases")
