@echo off
REM Installs the validation kit into a private folder (.venv). Needs Python 3.11+ and FFmpeg on PATH.
echo Checking Python...
python --version
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and tick "Add Python to PATH".
  pause & exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo WARNING: ffmpeg was not found. Install FFmpeg from https://ffmpeg.org/download.html and add it to PATH,
  echo          then open a NEW command window. The kit needs it to check and compare video.
)
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements_kit.txt
echo.
echo Done. Next:  run_kit.bat --after deleted.dd --clip clip.mp4 --out result
pause
