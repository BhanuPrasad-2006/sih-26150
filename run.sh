#!/usr/bin/env bash
set -e

SIH_PORT="${SIH_PORT:-8000}"
if [ "$SIH_TLS" = "1" ]; then SIH_SCHEME=https; else SIH_SCHEME=http; fi
SIH_URL="$SIH_SCHEME://127.0.0.1:$SIH_PORT"

echo "Starting DVR/NVR Forensic Tool at $SIH_URL ..."
echo "Your browser will open automatically once it is ready."
echo "Keep this terminal open while you work — closing it (or Ctrl+C) stops the tool."
echo

.venv/bin/python backend/startup_check.py

# Opens the browser as soon as the server answers, in a background helper — the server itself
# still runs in THIS terminal, in the foreground, same as Jupyter Notebook does.
.venv/bin/python tools/open_when_ready.py "$SIH_URL" &

if [ "$SIH_TLS" = "1" ]; then
  .venv/bin/python -m backend.serve
else
  .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "$SIH_PORT"
fi
