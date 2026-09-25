"""
serve.py — Start the server, optionally over HTTPS.   python -m backend.serve

  SIH_TLS=1     serve HTTPS with a local self-signed certificate (see backend/tls.py)
  SIH_HOST      bind address (default 127.0.0.1; anything else prints the warning in main.py)
  SIH_PORT      port (default 8000)
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("SIH_HOST", "127.0.0.1")
    port = int(os.environ.get("SIH_PORT", "8000"))
    kwargs: dict = {}
    if os.environ.get("SIH_TLS", "") == "1":
        from backend.tls import ensure_cert
        cert, key = ensure_cert()
        kwargs.update(ssl_certfile=str(cert), ssl_keyfile=str(key))
        print(f"HTTPS on https://{host}:{port}  (certificate: {cert})")
    uvicorn.run("backend.main:app", host=host, port=port, **kwargs)


if __name__ == "__main__":
    main()
