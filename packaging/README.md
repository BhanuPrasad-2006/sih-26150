# Building the Windows installer

Produces a normal double-click installer (`SIH-Forensic-Tool-Setup-<version>.exe`): welcome page,
a Terms and Conditions page the user must accept, an install-location page, a Start Menu folder
page, an optional Desktop shortcut, then installs and offers to launch the app. Nothing here is
committed to the repository except this folder's source files — the fetched ffmpeg binaries and
every build output are all gitignored (the ffmpeg binaries alone are ~200 MB).

## Requirements (Windows only — this builds a Windows installer)

- Python 3.11+ with this project's `requirements.txt` installed (the normal dev setup)
- `pip install pyinstaller`
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`)
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` set in `.env`  
  Get them from: **Supabase Dashboard → Settings → API**  
  (`Project URL` and `anon public` key — client-safe credentials, no Postgres password needed)

## Build

From the repository root:

```cmd
REM Step 1: Fetch bundled ffmpeg binaries (~200 MB, downloaded once)
python packaging\fetch_ffmpeg.py

REM Step 2: Bake client-safe Supabase credentials into the frozen build
REM (reads SUPABASE_URL + SUPABASE_ANON_KEY from .env — NOT the Postgres password)
python packaging\bundle_env.py

REM Step 3: Build the frozen app with PyInstaller
pyinstaller packaging\sih_desktop.spec --noconfirm --distpath packaging\dist --workpath packaging\build

REM Step 4: Wrap into a Windows installer with Inno Setup
"C:\Users\%USERNAME%\AppData\Local\Programs\Inno Setup 6\ISCC.exe" packaging\sih_installer.iss
```

The finished installer is written to `packaging\Output\SIH-Forensic-Tool-Setup-<version>.exe`,
where `<version>` is read from the repository's own `VERSION` file — bump that file, rebuild, and
the installer's filename and the app's in-app version display change together automatically.

## What gets bundled

- The Python app itself (`launch_desktop.py` -> `backend.desktop_app.main()`), as a "onedir"
  build (a folder, not one giant self-extracting exe — this starts noticeably faster)
- `backend/cv_models/*.onnx` (the face/object detection models)
- `frontend/` (the whole static frontend)
- `ffmpeg.exe` / `ffprobe.exe` (gyan.dev's "essentials" static build). `backend/desktop_app.py`'s
  `_ensure_ffmpeg_on_path()` only adds these to `PATH` if the machine doesn't already have
  `ffmpeg`/`ffprobe` on `PATH` — a system install is always preferred when present.

## Why a real installer needed real testing, not just a build that completes

A `pyinstaller` run finishing without errors does not mean the frozen app actually works — path
resolution for bundled data files, uvicorn's runtime module selection, and pywebview's Windows
backend are all things that can silently break only once you try to run the result. Before
relying on this, verify (again) after any change to `sih_desktop.spec`:

```powershell
# 1. Build (see above), then run the onedir build directly:
$env:SIH_PORT="8098"; $env:DATABASE_URL=""
& "packaging\dist\SIH Forensic Tool\SIH Forensic Tool.exe"
# -> a native window titled "SIH Forensic Tool - DVR/NVR Analysis (SIH26150)" should open;
#    curl http://127.0.0.1:8098/api/version should return the VERSION file's contents.

# 2. Build the installer (see above), then a real silent install + launch + uninstall:
& "packaging\Output\SIH-Forensic-Tool-Setup-<version>.exe" /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\temp\sih_test_install"
& "C:\temp\sih_test_install\SIH Forensic Tool.exe"    # same checks as step 1
& "C:\temp\sih_test_install\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

## Known limitations

- **Windows only.** macOS (`.dmg` / `.app`, via `py2app`) and Linux (`.deb` / `AppImage`) builds
  would need writing and testing on those OSes — nothing here attempts that.
- **Size.** The installed app is roughly 200 MB before compression (the two bundled ffmpeg
  binaries and OpenCV account for most of it); the compressed installer download is roughly
  190 MB. This is a real, honest size for a CV/media tool, not an oversight to "fix" later.
- **The WebView2 runtime itself is not bundled** — it ships with Windows 10/11 and Edge on
  effectively every real machine already, so this installer does not chain-install it. On the
  rare machine missing it entirely, `backend/desktop_app.py` falls back to opening the app in the
  default browser instead of failing.
- **AppId** in `sih_installer.iss` is a fixed GUID so re-running a newer installer upgrades the
  same install rather than creating a second copy — do not change it casually.
