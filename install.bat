@echo off
REM SIH26150 - DVR/NVR Forensic Tool - Windows installer
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

echo [1/5] Creating virtual environment...
python -m venv .venv
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [2/5] Installing dependencies...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [3/5] Installing the desktop-window component (optional)...
.venv\Scripts\pip install pywebview -q
if errorlevel 1 (
    echo   (Could not install it - the tool will still work, opening in your browser instead)
)

echo [4/5] Running startup check...
.venv\Scripts\python backend\startup_check.py

echo [5/5] Creating a Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut((Join-Path $ws.SpecialFolders('Desktop') 'SIH Forensic Tool.lnk'));" ^
  "$lnk.TargetPath = (Join-Path (Get-Location) 'run.bat');" ^
  "$lnk.WorkingDirectory = (Get-Location).Path;" ^
  "$lnk.Description = 'DVR/NVR Forensic Analysis Tool (SIH26150)';" ^
  "$lnk.WindowStyle = 1;" ^
  "$lnk.Save()"
if errorlevel 1 (
    echo   (Could not create the shortcut automatically - you can still start the tool with run.bat)
) else (
    echo   Shortcut created on your Desktop: "SIH Forensic Tool"
)

echo.
echo Done. Double-click the "SIH Forensic Tool" Desktop shortcut, or run  run.bat  to start it.
echo It opens as its own app window - no browser, no address bar.
pause
