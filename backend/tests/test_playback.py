"""In-browser playback of an exported segment: GET /api/cases/{id}/video/{segment}.
The endpoint is read-only, needs a session, supports Range requests (seeking) and only serves the file recorded
for that segment when it sits inside the case's exports folder."""

import hashlib
import os
import subprocess
import time

import pytest

from backend.exporter import ffmpeg_available, ffprobe_available
from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET

pytestmark = pytest.mark.skipif(not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH")


@pytest.fixture()
def exported(auth_client, temp_dir):
    """A case with one carved-and-exported segment; returns (case_id, segment dict, mp4 bytes)."""
    h264 = os.path.join(temp_dir, "clip.h264")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", h264], check=True)
    with open(h264, "rb") as fh:
        stream = fh.read()
    img = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    img += HIKV_MASTER_SECTOR_MAGIC + b"\x00" * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    img += b"\xCC" * 4096 + stream + b"\xCC" * 4096
    disk = os.path.join(temp_dir, "play.dd")
    with open(disk, "wb") as fh:
        fh.write(bytes(img))

    case_id = auth_client.post("/api/cases", json={"case_number": "PLAY-001", "examiner": "Tester", "notes": ""}).json()["case_id"]
    assert auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": disk}).status_code == 200
    assert auth_client.post(f"/api/cases/{case_id}/scan").json()["status"] == "started"
    segments = []
    for _ in range(100):
        segments = auth_client.get(f"/api/cases/{case_id}/segments").json()
        if segments:
            break
        time.sleep(0.1)
    seg = segments[0]
    exp = auth_client.post(f"/api/cases/{case_id}/export/{seg['segment_id']}").json()
    assert "error" not in exp["detail"], exp["detail"]
    with open(exp["detail"]["export_path"], "rb") as fh:
        return case_id, exp["segment"], fh.read()


def _stored_segment(case_id):
    import backend.main as m
    return m.db.list_segments_for_evidence(m.db.list_evidence_for_case(case_id)[0].evidence_id)[0]


def test_exported_segment_plays_and_matches_the_exported_file(auth_client, exported):
    case_id, seg, mp4 = exported
    r = auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["cache-control"] == "no-store"
    assert r.content == mp4


def test_range_requests_work_so_seeking_works(auth_client, exported):
    case_id, seg, mp4 = exported
    r = auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.content == mp4[:100]
    assert r.headers["content-range"].startswith("bytes 0-99/")


def test_playing_a_segment_does_not_change_the_export(auth_client, exported):
    case_id, seg, mp4 = exported
    before = hashlib.sha256(mp4).hexdigest()
    auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}")
    path = auth_client.get(f"/api/cases/{case_id}/segments").json()[0]["export_path"]
    with open(path, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == before == seg["sha256"]


def test_segment_that_was_not_exported_is_refused(auth_client, exported):
    import backend.main as m
    case_id, seg, _ = exported
    stored = _stored_segment(case_id)
    stored.export_path = None
    m.db.save_segment(stored)
    r = auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}")
    assert r.status_code == 400 and "not been exported" in r.json()["detail"]


def test_unknown_segment_and_unknown_case_are_404(auth_client, exported):
    case_id, seg, _ = exported
    assert auth_client.get(f"/api/cases/{case_id}/video/no-such-segment").status_code == 404
    assert auth_client.get(f"/api/cases/no-such-case/video/{seg['segment_id']}").status_code == 404


def test_a_file_outside_the_case_exports_folder_is_never_served(auth_client, exported, temp_dir):
    """Even if a stored export path were tampered with, nothing outside this case's exports folder is served."""
    import backend.main as m
    case_id, seg, _ = exported
    outside = os.path.join(temp_dir, "outside.mp4")
    with open(outside, "wb") as fh:
        fh.write(b"NOT-A-CASE-FILE")
    stored = _stored_segment(case_id)
    stored.export_path = outside
    m.db.save_segment(stored)
    r = auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}")
    assert r.status_code == 403
    assert b"NOT-A-CASE-FILE" not in r.content


def test_a_missing_export_file_gives_a_clear_404(auth_client, exported):
    case_id, seg, _ = exported
    os.remove(auth_client.get(f"/api/cases/{case_id}/segments").json()[0]["export_path"])
    r = auth_client.get(f"/api/cases/{case_id}/video/{seg['segment_id']}")
    assert r.status_code == 404 and "missing" in r.json()["detail"]


def test_playback_needs_a_session(auth_client, exported):
    from fastapi.testclient import TestClient
    import backend.main as m
    case_id, seg, _ = exported
    with TestClient(m.app) as anonymous:                      # a client with no session cookie
        assert anonymous.get(f"/api/cases/{case_id}/video/{seg['segment_id']}").status_code == 401
