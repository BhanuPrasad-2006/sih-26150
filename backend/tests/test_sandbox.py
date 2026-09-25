"""Resource limits, secret scrubbing and protocol whitelisting for external media tools."""

import os
import shutil
import subprocess
import sys
import time

import pytest

from backend import sandbox
from backend.exporter import ffprobe_check, remux_h264_to_mp4

PY = sys.executable
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg needed")


def test_child_environment_has_no_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    monkeypatch.setenv("SIH_AUDIT_KEY", "topsecret")
    monkeypatch.setenv("MY_API_TOKEN", "abc")
    monkeypatch.setenv("HARMLESS_SETTING", "1")
    r = sandbox.run_limited([PY, "-c", "import os;print(sorted(k for k in os.environ if k in "
                            "('DATABASE_URL','SIH_AUDIT_KEY','MY_API_TOKEN','HARMLESS_SETTING')))"], timeout=30)
    assert r.returncode == 0 and "HARMLESS_SETTING" in r.stdout
    assert "DATABASE_URL" not in r.stdout and "SIH_AUDIT_KEY" not in r.stdout and "MY_API_TOKEN" not in r.stdout


def test_timeout_kills_the_process():
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        sandbox.run_limited([PY, "-c", "import time;time.sleep(60)"], timeout=1)
    assert time.monotonic() - t < 15


def test_memory_limit_stops_a_runaway_process():
    code = "x = bytearray(900*1024*1024); print('allocated')"
    r = sandbox.run_limited([PY, "-c", code], timeout=60, mem_mb=200)
    assert r.returncode != 0 and "allocated" not in (r.stdout or "")


def test_process_within_limits_runs_normally():
    r = sandbox.run_limited([PY, "-c", "print(40+2)"], timeout=30, mem_mb=512)
    assert r.returncode == 0 and r.stdout.strip() == "42"


@pytest.mark.skipif(os.name != "nt", reason="job-object rule is Windows-specific")
def test_windows_job_forbids_spawning_children():
    code = "import subprocess,sys;subprocess.run([sys.executable,'-c','print(1)']);print('child ran')"
    r = sandbox.run_limited([PY, "-c", code], timeout=30)
    assert "child ran" not in (r.stdout or "")


@needs_ffmpeg
def test_ffprobe_refuses_network_protocols_from_a_hostile_playlist(tmp_path):
    playlist = tmp_path / "evil.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/should-never-be-fetched.ts\n#EXT-X-ENDLIST\n")
    r = sandbox.run_limited(["ffprobe", "-v", "error", *sandbox.FFMPEG_SAFE_INPUT, str(playlist)], timeout=30)
    assert "not on whitelist 'file,pipe'" in (r.stderr or "")      # our setting is the one in force (default is file,crypto,data)
    ok, info = ffprobe_check(playlist)
    assert ok is False


@needs_ffmpeg
def test_normal_export_still_works_through_the_sandbox(tmp_path):
    raw = tmp_path / "a.h264"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", str(raw)], check=True)
    ok, msg = remux_h264_to_mp4(raw, tmp_path / "a.mp4")
    assert ok, msg
    good, info = ffprobe_check(tmp_path / "a.mp4")
    assert good and any(s["codec_type"] == "video" for s in info["streams"])


def test_opencv_capture_is_limited_to_local_files():
    import backend  # noqa: F401
    assert "protocol_whitelist;file" in os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
