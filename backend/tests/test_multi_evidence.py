"""Several disk images in ONE case: every action must act on the image (and segment) it was asked about, not on
whichever image was added last. (Before this was fixed, scan/export/analytics always used the newest image, so results
for an older image were missing or came from the wrong disk.)"""

import hashlib
import os
import subprocess
import time

import pytest

from backend.exporter import ffmpeg_available, ffprobe_available
from backend.plugins.constants import HIKV_MASTER_SECTOR_MAGIC, HIKV_MASTER_SECTOR_OFFSET

pytestmark = pytest.mark.skipif(not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH")

FILLER = bytes([0xCC])
ZERO = bytes([0])


def _disk(temp_dir, name, source):
    h264 = os.path.join(temp_dir, name + ".h264")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=duration=1:size=320x240:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", h264], check=True)
    with open(h264, "rb") as fh:
        stream = fh.read()
    img = bytearray(HIKV_MASTER_SECTOR_OFFSET)
    img += HIKV_MASTER_SECTOR_MAGIC + ZERO * (512 - len(HIKV_MASTER_SECTOR_MAGIC))
    img += FILLER * 4096 + stream + FILLER * 4096
    path = os.path.join(temp_dir, name + ".dd")
    with open(path, "wb") as fh:
        fh.write(bytes(img))
    return path


def _wait_scan(client, cid, evidence_id):
    for _ in range(200):
        ev = next(e for e in client.get(f"/api/cases/{cid}").json()["evidence"] if e["evidence_id"] == evidence_id)
        if ev["scan_status"] != "SCANNING":
            return ev
        time.sleep(0.1)
    raise AssertionError("scan did not finish")


@pytest.fixture()
def two_images(auth_client, temp_dir):
    cid = auth_client.post("/api/cases", json={"case_number": "MULTI-1", "examiner": "Tester", "notes": ""}).json()["case_id"]
    ids = []
    for name, source in (("first", "testsrc"), ("second", "smptebars")):
        r = auth_client.post(f"/api/cases/{cid}/evidence", json={"path": _disk(temp_dir, name, source)})
        assert r.status_code == 200
        ids.append(r.json()["evidence_id"])
    return cid, ids


def test_scan_acts_on_the_image_it_was_asked_about_not_the_newest(auth_client, two_images):
    cid, (first, second) = two_images
    assert auth_client.post(f"/api/cases/{cid}/scan", params={"evidence_id": first}).json()["evidence_id"] == first
    assert _wait_scan(auth_client, cid, first)["scan_status"] == "COMPLETED"
    detail = {e["evidence_id"]: e for e in auth_client.get(f"/api/cases/{cid}").json()["evidence"]}
    assert detail[second]["scan_status"] == "PENDING"                # the newer image was NOT scanned
    assert auth_client.get(f"/api/cases/{cid}/segments", params={"evidence_id": second}).json() == []


def test_unknown_evidence_id_is_404(auth_client, two_images):
    cid, _ = two_images
    assert auth_client.post(f"/api/cases/{cid}/scan", params={"evidence_id": "nope"}).status_code == 404


def test_export_and_analytics_work_for_an_older_image_after_a_newer_one_was_scanned(auth_client, two_images):
    cid, (first, second) = two_images
    for ev_id in (first, second):                                     # scan the older image first, then the newer
        auth_client.post(f"/api/cases/{cid}/scan", params={"evidence_id": ev_id})
        assert _wait_scan(auth_client, cid, ev_id)["scan_status"] == "COMPLETED"

    exports = {}
    for ev_id in (first, second):
        seg = auth_client.get(f"/api/cases/{cid}/segments", params={"evidence_id": ev_id}).json()[0]
        r = auth_client.post(f"/api/cases/{cid}/export/{seg['segment_id']}")
        assert r.status_code == 200, r.text                            # used to 404 or read the wrong image for `first`
        assert r.json()["detail"]["ffprobe_valid"] is True
        exports[ev_id] = (seg["segment_id"], r.json()["detail"]["export_path"])
        assert auth_client.post(f"/api/cases/{cid}/motion/{seg['segment_id']}").status_code == 200
        assert auth_client.post(f"/api/cases/{cid}/face-detect/{seg['segment_id']}").status_code == 200
        assert auth_client.post(f"/api/cases/{cid}/object-detect/{seg['segment_id']}").status_code == 200

    # each export came from its own disk: two different pictures give two different files
    digests = {k: hashlib.sha256(open(p, "rb").read()).hexdigest() for k, (_, p) in exports.items()}
    assert digests[first] != digests[second]


def test_verify_and_report_accept_the_evidence_id(auth_client, two_images):
    cid, (first, second) = two_images
    auth_client.post(f"/api/cases/{cid}/scan", params={"evidence_id": first})
    _wait_scan(auth_client, cid, first)
    v = auth_client.get(f"/api/cases/{cid}/verify", params={"evidence_id": first})
    assert v.status_code == 200 and v.json()["unchanged"] is True
    assert auth_client.get(f"/api/cases/{cid}/verify", params={"evidence_id": second}).status_code == 400   # never hashed
    assert auth_client.get(f"/api/cases/{cid}/report", params={"evidence_id": first}).status_code == 200
