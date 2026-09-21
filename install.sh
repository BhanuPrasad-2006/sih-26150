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

echo "[1/3] Creating virtual environment..."
python3 -m venv .venv

echo "[2/3] Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

echo "[3/3] Running startup check..."
.venv/bin/python backend/startup_check.py

echo
echo "Done. Run  ./run.sh  to start the server."
