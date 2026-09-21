#!/usr/bin/env bash
set -e
echo "Starting DVR/NVR Forensic Tool at http://127.0.0.1:8000 ..."
echo "Press Ctrl+C to stop."
.venv/bin/python backend/startup_check.py
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
