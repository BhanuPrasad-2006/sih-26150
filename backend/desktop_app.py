"""
desktop_app.py — run the tool as a native desktop window, not a browser tab.

    python -m backend.desktop_app

Starts the internal FastAPI server in a background thread, waits for it
to answer, then opens it in a native OS window via pywebview (WebView2 on Windows,
WebKit on macOS/Linux) — no address bar, no browser chrome, just the app.
Closing the window stops the server and exits.
"""

from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

# Redirect stdout / stderr if None (happens in PyInstaller Windows GUI mode)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

APP_TITLE = "A.E.G.I.S — DVR/NVR Forensic Analysis Tool (SIH26150)"
_STARTUP_ERROR: list[str] = []


def _get_log_file() -> Path:
    temp_dir = Path(os.environ.get("TEMP", "."))
    return temp_dir / "sih_forensic_desktop.log"


def _log(msg: str) -> None:
    try:
        with open(_get_log_file(), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _find_free_port(preferred: int = 8000) -> int:
    """Check if preferred port is available; if not, find an open ephemeral port."""
    if os.environ.get("SIH_PORT"):
        try:
            return int(os.environ["SIH_PORT"])
        except ValueError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_url() -> tuple[str, str, int, bool]:
    host = "127.0.0.1"
    port = _find_free_port(8000)
    tls = os.environ.get("SIH_TLS", "") == "1"
    scheme = "https" if tls else "http"
    return f"{scheme}://{host}:{port}", host, port, tls


def _run_server(host: str, port: int, tls: bool) -> None:
    try:
        import uvicorn
        from backend.main import app as fastapi_app

        kwargs: dict = {
            "log_config": None,  # Prevent crash when stdout/stderr are redirected in GUI mode
        }
        if tls:
            from backend.tls import ensure_cert
            cert, key = ensure_cert()
            kwargs.update(ssl_certfile=str(cert), ssl_keyfile=str(key))

        _log(f"Starting uvicorn server on {host}:{port}...")
        uvicorn.run(fastapi_app, host=host, port=port, log_level="warning", **kwargs)
    except Exception as exc:
        err_msg = traceback.format_exc()
        _log(f"Server startup exception: {err_msg}")
        _STARTUP_ERROR.append(err_msg)


def _wait_until_ready(url: str, timeout: float = 25.0) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    status_url = url.rstrip("/") + "/api/auth/status"
    if not status_url.startswith(("http://127.0.0.1:", "https://127.0.0.1:")):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _STARTUP_ERROR:
            _log("Server thread reported an error; aborting wait.")
            return False
        try:
            with urllib.request.urlopen(status_url, timeout=1, context=ctx) as resp:  # nosec B310
                if resp.status == 200:
                    _log(f"Server is responding at {url}")
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class _DesktopBridge:
    def pick_folder(self) -> str | None:
        import webview
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_file(self) -> str | None:
        import webview
        window = webview.windows[0]
        file_types = (
            "Forensic Disk Images (*.dd;*.img;*.raw;*.bin;*.001;*.iso;*.vmdk;*.e01;*.*)|"
            "*.dd;*.img;*.raw;*.bin;*.001;*.iso;*.vmdk;*.e01;*.*|"
            "All Files (*.*)|*.*"
        )
        result = window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(file_types,),
        )
        return result[0] if result else None


def _error_html(detail: str) -> str:
    log_path = str(_get_log_file())
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{APP_TITLE} - Error</title>
<style>
  body {{ background: #0b0f19; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; line-height: 1.6; }}
  .card {{ max-width: 650px; margin: 40px auto; background: #131b2e; border: 1px solid #1e293b; border-radius: 12px; padding: 32px; }}
  h2 {{ color: #ef4444; margin-top: 0; display: flex; align-items: center; gap: 10px; font-size: 1.4rem; }}
  p {{ color: #94a3b8; font-size: 0.95rem; }}
  pre {{ background: #070b14; border: 1px solid #1e293b; color: #f87171; padding: 14px; border-radius: 8px; font-size: 0.82rem; overflow-x: auto; white-space: pre-wrap; }}
  .tip {{ background: #1e293b; padding: 12px 16px; border-radius: 6px; font-size: 0.85rem; color: #cbd5e1; margin-top: 20px; }}
</style>
</head>
<body>
<div class="card">
  <h2>Internal Engine Failed to Start</h2>
  <p>The local forensic analysis engine could not complete initialization.</p>
  <pre>{detail or "The service did not respond within the startup timeout."}</pre>
  <div class="tip">
    Log file saved to:<br><code>{log_path}</code>
  </div>
</div>
</body>
</html>"""


def _run_desktop_window(url: str, error_msg: str | None = None) -> None:
    import webview

    if error_msg:
        html = _error_html(error_msg)
        webview.create_window(APP_TITLE, html=html, width=900, height=600)
    else:
        webview.create_window(
            APP_TITLE,
            url,
            width=1440,
            height=900,
            min_size=(1024, 700),
            js_api=_DesktopBridge(),
        )
    webview.start()


def _fall_back_to_browser(url: str) -> None:
    print("Desktop window mode is unavailable on this system — opening in your browser instead.")
    repo_root = Path(__file__).resolve().parent.parent
    subprocess.Popen([sys.executable, str(repo_root / "tools" / "open_when_ready.py"), url])


def _ensure_ffmpeg_on_path() -> None:
    import shutil
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [Path(meipass) / "ffmpeg"] if meipass else []
    candidates.append(Path(__file__).resolve().parent.parent / "packaging" / "vendor" / "ffmpeg")
    for candidate in candidates:
        exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        if (candidate / exe_name).is_file():
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            _log(f"Using bundled ffmpeg/ffprobe from {candidate}")
            return


def main() -> None:
    _log("=== SIH Forensic Tool Desktop Launch ===")
    _ensure_ffmpeg_on_path()
    url, host, port, tls = _server_url()
    _log(f"Allocated server URL: {url}")

    server_thread = threading.Thread(target=_run_server, args=(host, port, tls), daemon=True)
    server_thread.start()

    ready = _wait_until_ready(url)
    error_msg = "\n".join(_STARTUP_ERROR) if not ready else None

    if not ready:
        _log(f"Server failed to become ready: {error_msg}")

    try:
        import webview  # noqa: F401
    except Exception as exc:
        _log(f"pywebview import failed: {exc}")
        if ready:
            _fall_back_to_browser(url)
            server_thread.join()
        return

    try:
        _run_desktop_window(url, error_msg=error_msg)
    except Exception as exc:
        _log(f"Could not open native window: {exc}")
        if ready:
            _fall_back_to_browser(url)
            server_thread.join()


if __name__ == "__main__":
    main()
