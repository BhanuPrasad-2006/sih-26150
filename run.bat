@echo off
REM SIH26150 - start the forensic tool server (Windows)
title SIH Forensic Tool

if "%SIH_PORT%"=="" set SIH_PORT=8000
if "%SIH_TLS%"=="1" (set SIH_SCHEME=https) else (set SIH_SCHEME=http)
set SIH_URL=%SIH_SCHEME%://127.0.0.1:%SIH_PORT%

echo Starting DVR/NVR Forensic Tool at %SIH_URL% ...
echo Your browser will open automatically once it is ready.
echo Keep this window open while you work - closing it (or Ctrl+C) stops the tool.
echo.

.venv\Scripts\python backend\startup_check.py
if errorlevel 1 ( pause & exit /b 1 )

REM Opens the browser as soon as the server answers, in a background helper - the server
REM itself still runs in THIS window, in the foreground, same as Jupyter Notebook does.
start "" /min .venv\Scripts\python tools\open_when_ready.py %SIH_URL%

if "%SIH_TLS%"=="1" (
  .venv\Scripts\python -m backend.serve
) else (
  .venv\Scripts\uvicorn backend.main:app --host 127.0.0.1 --port %SIH_PORT%
)
