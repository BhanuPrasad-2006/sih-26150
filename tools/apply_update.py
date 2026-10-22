"""
apply_update.py — pulls the latest code, reinstalls dependencies, and relaunches the app.

Spawned by POST /api/update/apply. Updates to the latest version directly from GitHub
without requiring manual re-download from the website.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_ROOT / "update.log"


def _log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
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
    _log("=== Update to latest version requested ===")

    # Wait for the old server process to exit and release ports / file locks
    time.sleep(2.5)

    if (REPO_ROOT / ".git").exists():
        _log("Git repository detected. Fetching origin...")
        ok, out = _run(["git", "fetch", "origin"])
        _log(f"git fetch origin: {'ok' if ok else 'FAILED'}\n{out}")

        # Check active branch
        _, current_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        current_branch = current_branch.strip() or "main"
        _log(f"Active branch: {current_branch}")

        if current_branch == "main":
            ok, out = _run(["git", "pull", "--ff-only", "origin", "main"])
        else:
            # Pull updates from origin/main into current branch
            ok, out = _run(["git", "pull", "origin", "main", "--no-rebase"])
            if not ok:
                ok, out = _run(["git", "merge", "origin/main", "-m", "Auto-update from origin/main"])

        _log(f"Git pull result: {'ok' if ok else 'FAILED'}\n{out}")

        # Install any updated dependencies
        requirements_file = REPO_ROOT / "requirements.txt"
        if requirements_file.is_file():
            ok, out = _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            _log(f"pip install: {'ok' if ok else 'FAILED'}\n{out[-1000:]}")

    # Relaunch the application
    run_bat = REPO_ROOT / "run.bat"
    desktop_exe = REPO_ROOT / "SIH Forensic Tool.exe"

    if desktop_exe.is_file():
        _log("Relaunching installed executable: SIH Forensic Tool.exe")
        subprocess.Popen([str(desktop_exe)], cwd=REPO_ROOT)
    elif run_bat.is_file() and sys.platform == "win32":
        _log("Relaunching via run.bat...")
        subprocess.Popen(["cmd.exe", "/c", str(run_bat)], cwd=REPO_ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        _log("Relaunching backend.desktop_app...")
        subprocess.Popen(
            [sys.executable, "-m", "backend.desktop_app"],
            cwd=REPO_ROOT,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
        )

    _log("=== Update finished successfully ===")


if __name__ == "__main__":
    main()