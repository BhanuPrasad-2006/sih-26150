"""
launch_desktop.py — the Windows installer's entry point.

Lives at the repository root (a sibling of the backend/ package), not inside backend/, on purpose:
PyInstaller adds the entry script's OWN directory to sys.path, not the repository root. An entry
script inside backend/ would then be unable to `import backend...` (it would look for a
backend/backend/ package). Putting this one file here instead means `import backend` resolves
correctly both in a normal dev checkout and inside the frozen build.

For everyday development, `python -m backend.desktop_app` (run by run.bat / run.sh) is still the
normal way to run this — this file exists only for PyInstaller to point at.
"""

from backend.desktop_app import main

if __name__ == "__main__":
    main()
