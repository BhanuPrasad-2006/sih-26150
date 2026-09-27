#!/usr/bin/env bash
set -e

echo "Starting DVR/NVR Forensic Tool ..."
echo "A window will open shortly. Closing it stops the tool."
echo

.venv/bin/python backend/startup_check.py

# Opens as a native desktop window (WebKit). If that is not available on this machine
# (e.g. the optional GTK/WebKit packages were not installed), backend.desktop_app falls
# back to opening in the default browser instead.
.venv/bin/python -m backend.desktop_app
