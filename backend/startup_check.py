"""
startup_check.py — Run this before starting the server.

Checks:
  1. Python version >= 3.11
  2. ffmpeg on PATH (needed for export and ffprobe validation)
  3. ffprobe on PATH (needed to validate exported files)
  4. Required Python packages are importable

Usage:
  python backend/startup_check.py
  (or: python -m backend.startup_check)
"""

import sys
import shutil
import subprocess
import importlib


def check_python_version() -> bool:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 11)
    status = "✓" if ok else "✗ FAIL"
    print(f"  {status}  Python {major}.{minor} (need 3.11+)")
    if not ok:
        print("       Install Python 3.11 or newer: https://python.org/downloads/")
    return ok


def check_binary(name: str, version_flag: str = "-version") -> bool:
    path = shutil.which(name)
    if not path:
        print(f"  ✗ FAIL  {name} not found on PATH")
        print(f"          Install from https://ffmpeg.org/download.html")
        print(f"          After installing, add the bin/ folder to your system PATH.")
        return False
    try:
        result = subprocess.run(
            [name, version_flag],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = (result.stdout or result.stderr or "").splitlines()[0] if (result.stdout or result.stderr) else "(no output)"
        print(f"  ✓  {name} found: {first_line[:80]}")
        return True
    except Exception as e:
        print(f"  ✗ FAIL  {name} found but failed to run: {e}")
        return False


def check_package(pkg: str, install_name: str | None = None) -> bool:
    try:
        importlib.import_module(pkg)
        print(f"  ✓  {pkg}")
        return True
    except ImportError:
        label = install_name or pkg
        print(f"  ✗ FAIL  {pkg} not installed  →  pip install {label}")
        return False


def check_case_dir() -> None:
    """Warn if the configured case directory is inside OneDrive."""
    import os
    case_dir = os.environ.get("FORENSIC_CASE_DIR", "")
    if not case_dir:
        if os.name == "nt":
            case_dir = r"C:\sih_cases"
        else:
            case_dir = os.path.expanduser("~/sih_cases")
        print(f"  ℹ  Case directory (default): {case_dir}")

    else:
        print(f"  ℹ  Case directory (FORENSIC_CASE_DIR): {case_dir}")

    if "onedrive" in case_dir.lower():
        print(
            "  ⚠ WARNING: Case directory is inside OneDrive.\n"
            "             Disk images and exported files inside OneDrive will be\n"
            "             uploaded to the cloud, breaking the offline / privacy requirement.\n"
            "             Set FORENSIC_CASE_DIR to a local path, e.g.:\n"
            "               Windows: C:\\forensic_cases\n"
            "               Linux  : /opt/forensic_cases"
        )


def main() -> int:
    print("=" * 60)
    print("  SIH26150 — DVR/NVR Forensic Tool — startup check")
    print("=" * 60)

    all_ok = True

    print("\n[1] Python version")
    all_ok &= check_python_version()

    print("\n[2] External binaries")
    all_ok &= check_binary("ffmpeg")
    all_ok &= check_binary("ffprobe")

    print("\n[3] Python packages")
    packages = [
        ("fastapi",       "fastapi"),
        ("uvicorn",       "uvicorn[standard]"),
        ("aiosqlite",     "aiosqlite"),
        ("reportlab",     "reportlab"),
        ("multipart",     "python-multipart"),
        ("aiofiles",      "aiofiles"),
        ("pydantic",      "pydantic"),
    ]
    for mod, pip_name in packages:
        all_ok &= check_package(mod, pip_name)

    print("\n[4] Case directory")
    check_case_dir()

    print()
    if all_ok:
        print("✓  All checks passed. Safe to start the server.\n")
        return 0
    else:
        print("✗  One or more checks failed. Fix the issues above before starting.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
