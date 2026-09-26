"""A scanned image that yielded nothing must not look "never scanned": the case detail reports NO_VIDEO / FAILED
with a plain-language reason, and a later successful scan replaces that verdict."""

import os
import subprocess
import time

import pytest

from backend.exporter import ffmpeg_available, ffprobe_available
from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET

FILLER = bytes([0xCC])
ZERO = bytes([0])


def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def _case_with_image(auth_client, path, number):
    cid = auth_client.post("/api/cases", json={"case_number": number, "examiner": "Tester", "notes": ""}).json()["case_id"]
    assert auth_client.post(f"/api/cases/{cid}/evidence", json={"path": path}).status_code == 200
    return cid


def _evidence(auth_client, cid):
    return auth_client.get(f"/api/cases/{cid}").json()["evidence"][0]


def _scan_and_wait(auth_client, cid):
    assert auth_client.post(f"/api/cases/{cid}/scan").json()["status"] == "started"
    for _ in range(150):
        ev = _evidence(auth_client, cid)
        if ev["scan_status"] != "SCANNING":
            return ev
        time.sleep(0.1)
    raise AssertionError("scan did not finish")


def test_new_image_is_pending_before_any_scan(auth_client, temp_dir):
    path = os.path.join(temp_dir, "blank.dd")
    _write(path, ZERO * 65536)
    cid = _case_with_image(auth_client, path, "OUT-0")
    ev = _evidence(auth_client, cid)
    assert ev["scan_status"] == "PENDING" and ev["scan_message"] is None


def test_image_with_no_video_reports_no_video_with_a_plain_reason(auth_client, temp_dir):
    path = os.path.join(temp_dir, "nothing.dd")
    _write(path, FILLER * 262144)
    cid = _case_with_image(auth_client, path, "OUT-1")
    ev = _scan_and_wait(auth_client, cid)
    assert ev["scan_status"] == "NO_VIDEO"
    assert "No video could be recovered" in ev["scan_message"]
    assert "confidence" not in ev["scan_message"].lower()          # no raw "0%" jargon in the user-facing text
    audit = auth_client.get(f"/api/cases/{cid}/audit").json()["entries"]
    assert any(e["action"] == "scan_no_video" and "best brand confidence" in e["details"] for e in audit)


def test_verdict_is_stored_not_held_in_memory(auth_client, temp_dir):
    """A restart clears the in-memory state; the verdict must still be there."""
    import backend.main as m
    path = os.path.join(temp_dir, "nothing2.dd")
    _write(path, FILLER * 262144)
    cid = _case_with_image(auth_client, path, "OUT-2")
    _scan_and_wait(auth_client, cid)
    m._active_scan_evidence.clear()
    assert _evidence(auth_client, cid)["scan_status"] == "NO_VIDEO"


@pytest.mark.skipif(not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH")
def test_a_later_successful_scan_replaces_an_old_no_video_verdict(auth_client, temp_dir):
    import backend.main as m
    h264 = os.path.join(temp_dir, "clip.h264")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", h264], check=True)
    with open(h264, "rb") as fh:
        stream = fh.read()
    img = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    img += HIKV_MASTER_SECTOR_MAGIC + ZERO * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    img += FILLER * 4096 + stream + FILLER * 4096
    path = os.path.join(temp_dir, "later.dd")
    _write(path, bytes(img))
    cid = _case_with_image(auth_client, path, "OUT-3")
    evidence_id = _evidence(auth_client, cid)["evidence_id"]

    m._save_scan_outcome(evidence_id, "NO_VIDEO", "left over from an earlier scan")
    assert _evidence(auth_client, cid)["scan_status"] == "NO_VIDEO"
    ev = _scan_and_wait(auth_client, cid)
    assert ev["scan_status"] == "COMPLETED" and ev["scan_message"] is None
    assert m._load_scan_outcome(evidence_id) is None


def test_unreadable_image_reports_failed(auth_client, temp_dir):
    path = os.path.join(temp_dir, "vanishes.dd")
    _write(path, FILLER * 4096)
    cid = _case_with_image(auth_client, path, "OUT-4")
    os.remove(path)                                               # the file disappears before the scan
    ev = _scan_and_wait(auth_client, cid)
    assert ev["scan_status"] == "FAILED" and ev["scan_message"]
