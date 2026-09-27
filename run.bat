@echo off
REM SIH26150 - start the forensic tool as a desktop app (Windows)
title SIH Forensic Tool

echo Starting DVR/NVR Forensic Tool ...
echo A window will open shortly. Closing it stops the tool.
echo.

.venv\Scripts\python backend\startup_check.py
if errorlevel 1 ( pause & exit /b 1 )

REM Opens as a native desktop window (WebView2). If that is not available on this machine,
REM backend.desktop_app falls back to opening in the default browser instead.
.venv\Scripts\python -m backend.desktop_app
