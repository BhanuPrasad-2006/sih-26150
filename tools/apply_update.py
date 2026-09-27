"""
apply_update.py — pulls the latest code, reinstalls dependencies, and relaunches the app.

Run detached, spawned by POST /api/update/apply just before that server process exits. Waits for
the old process to fully release its files, then:
    git fetch origin
    git merge --ff-only origin/main      (never rewrites local history; refuses a non-fast-forward
                                           merge rather than risk discarding anything)
    pip install -r requirements.txt      (best effort — logged, not fatal on its own)
    relaunch: python -m backend.desktop_app

Everything is logged to <repo_root>/update.log so a failed update can be diagnosed after the
fact; this is a best-effort mechanism for a hackathon-stage tool, not a guaranteed atomic upgrade.
On any failure up to the relaunch step, it still relaunches the app (on whatever code is on disk)
rather than leaving the user with nothing running.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_ROOT / "update.log"


def _log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)
    print(line, end="")


def _run(args: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
        ok = result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "")
        return ok, output.strip()
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    _log("=== Update requested ===")

    # Give the old server process (and its still-open .venv DLLs on Windows) time to fully exit
    # before we try to overwrite anything it had loaded.
    time.sleep(3)

    ok, out = _run(["git", "fetch", "origin"])
    _log(f"git fetch origin: {'ok' if ok else 'FAILED'}\n{out}")

    if ok:
        ok, out = _run(["git", "merge", "--ff-only", "origin/main"])
        _log(f"git merge --ff-only origin/main: {'ok' if ok else 'FAILED (not fast-forward, or no changes — left untouched)'}\n{out}")

    ok, out = _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    _log(f"pip install -r requirements.txt: {'ok' if ok else 'FAILED (continuing with what is already installed)'}\n{out[-2000:]}")

    _log("Relaunching backend.desktop_app ...")
    subprocess.Popen(
        [sys.executable, "-m", "backend.desktop_app"],
        cwd=REPO_ROOT,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
    )
    _log("=== Update finished ===")


if __name__ == "__main__":
    main()
