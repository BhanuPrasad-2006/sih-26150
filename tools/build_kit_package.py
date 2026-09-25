"""
build_kit_package.py — Build the downloadable validation kit and the download page.

    python tools/build_kit_package.py

Writes  docs/download/sih-validation-kit.zip  (deterministic: the same sources always give the same SHA-256) and
renders  docs/index.html  from tools/kit_package/index.template.html with the zip's size, hash and version, so the page
and the file can never disagree. Serve the docs/ folder with GitHub Pages (Settings -> Pages -> main /docs).

Only what the kit needs goes into the zip: the recovery modules, no web app, no models, no tests, no keys.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "tools" / "kit_package"
OUT_DIR = ROOT / "docs" / "download"
ZIP_NAME = "sih-validation-kit.zip"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)          # constant timestamps make the archive reproducible

# backend modules the kit imports (verified by tests/test_kit_package.py: the kit runs with no web dependencies)
BACKEND_FILES = [
    "__init__.py", "accuracy.py", "acquisition.py", "exporter.py", "models.py", "pipeline.py",
    "reconstructor.py", "sandbox.py", "validation_kit.py",
]
PLUGIN_FILES = [p.name for p in sorted((ROOT / "backend" / "plugins").glob("*.py"))]

EXTRA_FILES = {            # archive name -> source
    "README_FIRST.txt": PKG / "README_FIRST.txt",
    "requirements_kit.txt": PKG / "requirements_kit.txt",
    "install_kit.bat": PKG / "install_kit.bat",
    "run_kit.bat": PKG / "run_kit.bat",
    "install_kit.sh": PKG / "install_kit.sh",
    "run_kit.sh": PKG / "run_kit.sh",
    "GUIDE.md": ROOT / "docs" / "VALIDATION_KIT.md",
    "validation_notes_template.json": ROOT / "docs" / "validation_notes_template.json",
}


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,  # nosec B603 B607
                              text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def collect() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in BACKEND_FILES:
        files[f"backend/{name}"] = (ROOT / "backend" / name).read_bytes()
    for name in PLUGIN_FILES:
        files[f"backend/plugins/{name}"] = (ROOT / "backend" / "plugins" / name).read_bytes()
    for arc, src in EXTRA_FILES.items():
        data = src.read_bytes()
        if arc.endswith((".sh", ".txt", ".md", ".json", ".bat")):
            data = data.replace(b"\r\n", b"\n")                     # one line-ending style; .bat still runs with LF
            if arc.endswith(".bat"):
                data = data.replace(b"\n", b"\r\n")                 # Windows batch files want CRLF
        files[arc] = data
    files["VERSION.txt"] = (f"SIH DVR/NVR Forensic Tool - validation kit\ncommit {_git_commit()}\n").encode()
    return files


def build_zip(files: dict[str, bytes], dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"sih-validation-kit/{name}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".sh") else 0o644) << 16
            z.writestr(info, files[name])
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def render_page(sha256: str, size: int, version: str) -> Path:
    tpl = (PKG / "index.template.html").read_text(encoding="utf-8")
    html = (tpl.replace("{{SHA256}}", sha256).replace("{{SIZE_KB}}", f"{size / 1024:.0f}")
               .replace("{{VERSION}}", version).replace("{{DATE}}", datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    out = ROOT / "docs" / "index.html"
    out.write_text(html, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")   # serve files as they are, no Jekyll processing
    return out


def main() -> int:
    dest = OUT_DIR / ZIP_NAME
    sha = build_zip(collect(), dest)
    (OUT_DIR / (ZIP_NAME + ".sha256")).write_text(f"{sha}  {ZIP_NAME}\n", encoding="utf-8")
    page = render_page(sha, dest.stat().st_size, _git_commit())
    print(f"{dest}  {dest.stat().st_size:,} bytes  sha256 {sha}")
    print(f"page: {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
