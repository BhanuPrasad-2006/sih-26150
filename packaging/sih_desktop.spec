# sih_desktop.spec — PyInstaller build for the Windows desktop app.
#
# Build (from the repository root):
#   python packaging/fetch_ffmpeg.py
#   pyinstaller packaging/sih_desktop.spec --noconfirm
#
# Produces a "onedir" build (a folder, not one giant exe) at packaging/dist/SIH Forensic Tool/ —
# onedir starts noticeably faster than a onefile build, which must self-extract on every launch.
# Inno Setup (packaging/sih_installer.iss) then wraps that whole folder into one installer .exe.

import sys
from pathlib import Path

block_cipher = None
REPO_ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is injected by PyInstaller

datas = [
    (str(REPO_ROOT / "VERSION"), "."),
    (str(REPO_ROOT / "backend" / "cv_models"), "backend/cv_models"),
    (str(REPO_ROOT / "frontend"), "frontend"),
]
ffmpeg_dir = REPO_ROOT / "packaging" / "vendor" / "ffmpeg"
if (ffmpeg_dir / "ffmpeg.exe").is_file():
    datas.append((str(ffmpeg_dir), "ffmpeg"))
else:
    print("WARNING: packaging/vendor/ffmpeg not found — run packaging/fetch_ffmpeg.py first. "
          "Building without it; the installed app will need ffmpeg/ffprobe already on PATH.",
          file=sys.stderr)

hiddenimports = [
    # uvicorn picks its event loop / HTTP implementation by name at runtime (uvloop is not used
    # on Windows; these are the ones that matter here) — PyInstaller's static import scan does
    # not see that dynamic selection.
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # pywebview picks its Windows backend the same way.
    "webview",
    "webview.platforms.edgechromium",
    # Supabase client backend (anon key — no Postgres password).
    "supabase",
    "supabase._sync.client",
    "gotrue",
    "httpx",
    # Postgres direct connection (dev/server builds — kept for completeness).
    "psycopg2",
    # Bundled config written by packaging/bundle_env.py at build time.
    "backend._bundled_config",
]

a = Analysis(
    [str(REPO_ROOT / "launch_desktop.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["pytest", "pytest_asyncio"],  # dev/test-only; not needed at runtime
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SIH Forensic Tool",
    debug=False,
    strip=False,
    upx=False,
    console=False,   # no console window behind the app window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SIH Forensic Tool",
)
