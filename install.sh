#!/usr/bin/env bash
set -e

echo
echo "============================================================"
echo "  SIH26150 DVR/NVR Forensic Tool - Setup (Linux/macOS)"
echo "============================================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.11+."
  exit 1
fi

echo "[1/4] Creating virtual environment..."
python3 -m venv .venv

echo "[2/4] Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

echo "[3/4] Installing the desktop-window component (optional)..."
if .venv/bin/pip install pywebview -q; then
  echo "  Installed. On Linux it also needs GTK + WebKit2 (e.g. 'sudo apt install python3-gi gir1.2-webkit2-4.1'"
  echo "  on Debian/Ubuntu); on macOS it works out of the box. Without it, the tool opens in your browser instead."
else
  echo "  (Could not install it - the tool will still work, opening in your browser instead)"
fi

echo "[4/4] Running startup check..."
.venv/bin/python backend/startup_check.py

echo
echo "Done. Run  ./run.sh  to start the tool."
