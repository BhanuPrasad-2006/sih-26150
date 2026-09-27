"""
fetch_ffmpeg.py — downloads ffmpeg.exe / ffprobe.exe (Windows) into packaging/vendor/ffmpeg/.

Run once before building the installer:

    python packaging/fetch_ffmpeg.py

These binaries are NOT committed to the repository (~200 MB) — this script is the build step
that gets them locally, from gyan.dev's "essentials" static build (the same one many projects
use; still large because static ffmpeg builds statically link several codec libraries, but far
smaller than the "full" build, which is roughly double the size for codecs this project does not
use, e.g. dav1d/rav1e AV1 encoding).
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "ffmpeg"


def main() -> None:
    if (VENDOR_DIR / "ffmpeg.exe").is_file() and (VENDOR_DIR / "ffprobe.exe").is_file():
        print(f"Already present at {VENDOR_DIR} — delete that folder to force a re-download.")
        return

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = VENDOR_DIR / "_download.zip"
    print(f"Downloading {URL} ...")
    urllib.request.urlretrieve(URL, zip_path)  # nosec B310: fixed literal HTTPS URL, run by a developer, never attacker input

    print("Extracting ffmpeg.exe and ffprobe.exe ...")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            name = Path(member).name
            if name in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in member.replace("\\", "/"):
                with zf.open(member) as src, open(VENDOR_DIR / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  {name}")

    zip_path.unlink()

    missing = [n for n in ("ffmpeg.exe", "ffprobe.exe") if not (VENDOR_DIR / n).is_file()]
    if missing:
        print(f"ERROR: could not find {missing} in the downloaded archive.", file=sys.stderr)
        sys.exit(1)
    print(f"Done: {VENDOR_DIR}")


if __name__ == "__main__":
    main()
