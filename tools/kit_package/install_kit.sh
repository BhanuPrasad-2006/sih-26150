#!/usr/bin/env bash
# Installs the validation kit into a private folder (.venv). Needs Python 3.11+ and FFmpeg on PATH.
set -e
python3 --version
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found. Install it (for example: sudo apt install ffmpeg) and run this again."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_kit.txt
echo
echo "Done. Next:  ./run_kit.sh --after deleted.dd --clip clip.mp4 --out result"
