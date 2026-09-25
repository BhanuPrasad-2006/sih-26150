#!/usr/bin/env bash
# Usage: ./run_kit.sh --after deleted.dd --clip clip.mp4 [--before original.dd] [--notes notes.json] --out result
exec "$(dirname "$0")/.venv/bin/python" -m backend.validation_kit "$@"
