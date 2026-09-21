@echo off
REM SIH26150 — DVR/NVR Forensic Tool — Windows installer
echo.
echo ============================================================
echo   SIH26150 DVR/NVR Forensic Tool - Setup (Windows)
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on PATH. Install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
python -m venv .venv
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [2/3] Installing dependencies...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [3/3] Running startup check...
.venv\Scripts\python backend\startup_check.py

echo.
echo Done. Run  run.bat  to start the server.
pause
