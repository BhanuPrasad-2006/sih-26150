@echo off
REM Usage: run_kit.bat --after deleted.dd --clip clip.mp4 [--before original.dd] [--notes notes.json] --out result
.venv\Scripts\python -m backend.validation_kit %*
