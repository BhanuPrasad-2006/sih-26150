@echo off
REM SIH26150 — start the forensic tool server (Windows)
echo Starting DVR/NVR Forensic Tool at http://127.0.0.1:8000 ...
echo Press Ctrl+C to stop.
.venv\Scripts\python backend\startup_check.py
if errorlevel 1 ( pause & exit /b 1 )
.venv\Scripts\uvicorn backend.main:app --host 127.0.0.1 --port 8000
