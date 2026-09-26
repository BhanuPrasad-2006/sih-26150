# Hardened container for the forensic tool (optional). NOT tested in this repository's development
# environment (no Docker available there): build and try it on a scratch case before relying on it.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with no login shell
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin sih \n    && mkdir -p /data/cases /data/keys && chown -R sih /data
WORKDIR /app

COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt pyhanko

COPY backend ./backend
COPY frontend ./frontend

# Inside the container the server must listen on all interfaces; docker-compose publishes the port to the host's
# loopback only, and the Host header is still checked (127.0.0.1 / localhost).
ENV SIH_HOST=0.0.0.0 SIH_PORT=8000 FORENSIC_CASE_DIR=/data/cases SIH_KEY_DIR=/data/keys PYTHONUNBUFFERED=1
USER sih
EXPOSE 8000
CMD ["python", "-m", "backend.serve"]
