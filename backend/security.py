"""
security.py — Request-level hardening for the localhost forensic server.

  SecurityHeadersMiddleware  CSP, clickjacking, MIME-sniffing and referrer protection on every response.
  HostOriginMiddleware       Rejects requests whose Host is not a local name (DNS-rebinding defence) and
                             state-changing requests whose Origin / Sec-Fetch-Site says cross-site (CSRF).
  ensure_path_allowed        Optional allow-list for server-side file paths the examiner can point the tool at.

The front end uses no inline event handlers or inline scripts (clicks are delegated via data-nav / data-act),
so script-src is strictly 'self'. Styles still allow 'unsafe-inline' because the UI sets style attributes; that
is a much smaller risk (no script execution) and is the remaining CSP concession.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}   # 'testserver' is Starlette's TestClient name
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def allowed_hosts() -> set[str]:
    hosts = set(_LOCAL_HOSTS)
    extra = os.environ.get("SIH_ALLOWED_HOSTS", "")
    hosts.update(h.strip().lower() for h in extra.split(",") if h.strip())
    sih_host = os.environ.get("SIH_HOST", "").strip().lower()
    if sih_host and sih_host not in ("0.0.0.0", "::"):   # nosec B104  (a comparison, not a bind)
        hosts.add(sih_host)                       # the operator explicitly chose this bind address
    return hosts


def _hostname(host_header: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1'; '[::1]:8000' -> '::1'."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:].split("]")[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class HostOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host_header = request.headers.get("host", "")
        if _hostname(host_header) not in allowed_hosts():
            return JSONResponse({"detail": "Host not allowed."}, status_code=400)

        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin != "null":
                if urlsplit(origin).netloc.lower() != host_header.strip().lower():
                    return JSONResponse({"detail": "Cross-origin request blocked."}, status_code=403)
            elif origin == "null":
                return JSONResponse({"detail": "Cross-origin request blocked."}, status_code=403)
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            if k == "Cache-Control" and "cache-control" in response.headers:
                continue                              # keep the static files' own no-cache policy
            response.headers[k] = v
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path != "/api/docs":           # Swagger UI loads assets from a CDN
            response.headers["Content-Security-Policy"] = CSP
        return response


# ── Server-side path allow-list ───────────────────────────────────────────────

def evidence_roots() -> list[Path]:
    raw = os.environ.get("FORENSIC_EVIDENCE_ROOTS", "")
    return [Path(p).resolve() for p in raw.split(os.pathsep) if p.strip()]


def ensure_path_allowed(path: str | Path, always_allowed: list[Path] | None = None) -> None:
    """
    When FORENSIC_EVIDENCE_ROOTS is set (os.pathsep-separated folders), the server only reads evidence /
    original-image paths inside those folders (or `always_allowed`, e.g. the case folder). When unset, the
    tool behaves as a local single-user tool and any path the examiner types is accepted.
    Symlinks and '..' are resolved before the check.
    """
    roots = evidence_roots()
    if not roots:
        return
    resolved = Path(path).resolve()
    for root in roots + [p.resolve() for p in (always_allowed or [])]:
        if resolved.is_relative_to(root):
            return
    raise HTTPException(
        403,
        "This path is outside the folders the server is allowed to read "
        "(FORENSIC_EVIDENCE_ROOTS). Copy the image into an allowed folder or ask the administrator.",
    )
