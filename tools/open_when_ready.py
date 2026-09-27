"""
open_when_ready.py — wait for the local server to answer, then open it in the default browser.

Used by run.bat / run.sh so starting the tool feels like opening an app (Jupyter Notebook does
the same thing): the server keeps running in the terminal window that started it, and the
browser tab appears on its own a moment later, instead of the user having to type the address.

    python tools/open_when_ready.py http://127.0.0.1:8000

Polls the unauthenticated /api/auth/status endpoint for up to ~25 seconds, then opens the
browser regardless (if the server is unusually slow to start, the tab can just be refreshed).
"""

from __future__ import annotations

import ssl
import sys
import time
import urllib.request
import webbrowser

_TIMEOUT_SECONDS = 25
_POLL_INTERVAL = 0.5


def _unverified_context() -> ssl.SSLContext:
    # Only used to poll our own freshly-generated self-signed localhost certificate (SIH_TLS=1);
    # nothing sensitive is sent, and it is never used for anything other than this readiness check.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _server_is_up(status_url: str, ctx: ssl.SSLContext) -> bool:
    if not status_url.startswith(("http://127.0.0.1:", "https://127.0.0.1:")):
        # Only ever called with our own server's URL (see main()) — never attacker input — but
        # urlopen is only ever reached once the scheme and host have been checked, right here.
        return False
    try:
        with urllib.request.urlopen(status_url, timeout=1, context=ctx) as resp:  # nosec B310: scheme and host checked just above
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    status_url = url.rstrip("/") + "/api/auth/status"
    ctx = _unverified_context()

    deadline = time.time() + _TIMEOUT_SECONDS
    while time.time() < deadline:
        if _server_is_up(status_url, ctx):
            break
        time.sleep(_POLL_INTERVAL)

    webbrowser.open(url)


if __name__ == "__main__":
    main()
