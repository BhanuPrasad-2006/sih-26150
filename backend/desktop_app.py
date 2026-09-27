"""
desktop_app.py — run the tool as a native desktop window, not a browser tab.

    python -m backend.desktop_app

Starts the same FastAPI server as `python -m backend.serve` in a background thread, waits for it
to answer, then opens it in a native OS window via pywebview (WebView2 on Windows, WebKit on
macOS/Linux) — no address bar, no browser chrome, just the app. Closing the window stops the
server and exits, the same as any other installed desktop program (Wireshark, Autopsy, ...).

If pywebview or its OS component (e.g. the WebView2 runtime) is not available, this falls back
to the plain browser-tab mode (`backend.serve` + tools/open_when_ready.py) instead of failing
outright — run.bat / run.sh call this module unconditionally and rely on that fallback.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_TITLE = "SIH Forensic Tool — DVR/NVR Analysis (SIH26150)"


def _server_url() -> tuple[str, str, int, bool]:
    host = "127.0.0.1"
    port = int(os.environ.get("SIH_PORT", "8000"))
    tls = os.environ.get("SIH_TLS", "") == "1"
    scheme = "https" if tls else "http"
    return f"{scheme}://{host}:{port}", host, port, tls


def _run_server(host: str, port: int, tls: bool) -> None:
    import uvicorn
    # The app object is imported and passed directly (not the "backend.main:app" string form)
    # so this also works inside a frozen PyInstaller build, where a dynamic import-by-string at
    # runtime is not reliably discovered by PyInstaller's static analysis.
    from backend.main import app as fastapi_app

    kwargs: dict = {}
    if tls:
        from backend.tls import ensure_cert
        cert, key = ensure_cert()
        kwargs.update(ssl_certfile=str(cert), ssl_keyfile=str(key))
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning", **kwargs)


def _wait_until_ready(url: str, timeout: float = 25.0) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    status_url = url.rstrip("/") + "/api/auth/status"
    if not status_url.startswith(("http://127.0.0.1:", "https://127.0.0.1:")):
        # This is our own server's URL, built two lines above from SIH_PORT/SIH_TLS — never
        # attacker input — but urlopen is only ever called with that fixed, checked scheme+host.
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(status_url, timeout=1, context=ctx) as resp:  # nosec B310: scheme and host checked just above
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class _DesktopBridge:
    """Exposed to the page as window.pywebview.api.* — lets the first-run wizard open a real
    native folder-picker dialog instead of a plain text field (only possible in this desktop
    window; a plain browser tab has no such access and falls back to typing the path)."""

    def pick_folder(self) -> str | None:
        import webview
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def _run_desktop_window(url: str) -> None:
    import webview

    webview.create_window(APP_TITLE, url, width=1440, height=900, min_size=(1024, 700), js_api=_DesktopBridge())
    webview.start()


def _fall_back_to_browser(url: str) -> None:
    print("Desktop window mode is unavailable on this system — opening in your browser instead.")
    print("(For the native app window, install the WebView2 runtime, or run: pip install pywebview)")
    repo_root = Path(__file__).resolve().parent.parent
    subprocess.Popen([sys.executable, str(repo_root / "tools" / "open_when_ready.py"), url])


def _ensure_ffmpeg_on_path() -> None:
    """
    If ffmpeg/ffprobe are not already on PATH, add a bundled copy's folder to PATH for this
    process (a packaged installer ships one at <app>/ffmpeg/). Every ffmpeg/ffprobe call in this
    codebase already goes through PATH lookup (shutil.which / bare "ffmpeg" in subprocess argv),
    so this one check is all that is needed to make a bundled copy usable everywhere, with no
    other code path aware of where the binaries actually came from.
    """
    import shutil
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [Path(meipass) / "ffmpeg"] if meipass else []
    candidates.append(Path(__file__).resolve().parent.parent / "packaging" / "vendor" / "ffmpeg")
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file() if os.name == "nt" else (candidate / "ffmpeg").is_file():
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            print(f"Using bundled ffmpeg/ffprobe from {candidate}")
            return


def main() -> None:
    _ensure_ffmpeg_on_path()
    url, host, port, tls = _server_url()

    server_thread = threading.Thread(target=_run_server, args=(host, port, tls), daemon=True)
    server_thread.start()
    ready = _wait_until_ready(url)
    if not ready:
        print(f"Warning: the server did not answer within the timeout; opening {url} anyway.")

    try:
        import webview  # noqa: F401  (import check only — the real use is in _run_desktop_window)
    except Exception as exc:
        print(f"pywebview is not usable here ({exc}).")
        _fall_back_to_browser(url)
        server_thread.join()
        return

    try:
        _run_desktop_window(url)
    except Exception as exc:
        print(f"Could not open a native window ({exc}).")
        _fall_back_to_browser(url)
        server_thread.join()


if __name__ == "__main__":
    main()
