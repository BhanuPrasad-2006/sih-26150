"""The validation kit: image(s) + ground-truth clip in, finished validation report out.
No real recorder is available, so these use generated Dahua DHFS disks around real encoded video."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import validation_kit as K
from backend.plugins.constants import DHFS_DESC_SIZE
from backend.tests import test_dahua_dhfs as D

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="ffmpeg/ffprobe needed")

BASE = int(datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc).timestamp())


def _remux_to_mp4(h264: Path, mp4: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "h264", "-i", str(h264), "-c", "copy", str(mp4)], check=True)
    return mp4


def _wipe(disk: bytes) -> bytes:
    """Deletion as the recorder's menu might do it: every descriptor becomes 'free'; cluster data stays."""
    m = bytearray(disk)
    dt = D._DESC_SECTOR * 512
    for i in range(D._N_DESC):
        m[dt + i * DHFS_DESC_SIZE: dt + (i + 1) * DHFS_DESC_SIZE] = b"\xfe" + b"\x00" * (DHFS_DESC_SIZE - 1)
    return bytes(m)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("kitmedia")
    a = D._encode("testsrc", str(d / "a.h264"))
    b = D._encode("smptebars", str(d / "b.h264"))
    other = D._encode("testsrc2", str(d / "c.h264"))
    return {"dir": d, "a": a, "b": b,
            "truth_a": _remux_to_mp4(d / "a.h264", d / "truth_a.mp4"),
            "truth_other": _remux_to_mp4(d / "c.h264", d / "truth_other.mp4"),
            "dhav_a": D._dhav_stream(a, 0, BASE), "dhav_b": D._dhav_stream(b, 1, BASE + 3)}


def _disks(media, both: bool, tmp: Path):
    recs = []
    pos = 2
    for cam, key, t0 in ((1, "dhav_a", 0), (2, "dhav_b", 3)):
        if cam == 2 and not both:
            continue
        data = media[key]
        n = -(-len(data) // D._CL)
        recs.append(dict(camera=cam, data=data, clusters=list(range(pos, pos + n)), t0=t0))
        pos += n
    disk = D.build_dhfs_disk(recs)
    before, after = tmp / "before.dd", tmp / "after.dd"
    before.write_bytes(disk)
    after.write_bytes(_wipe(disk))
    return before, after


def _run(after, out, **kw):
    return K.run_validation(after, out, progress=lambda m: None, **kw)


def test_recovered_video_matching_the_clip_is_reported_as_matching(media, tmp_path):
    before, after = _disks(media, both=False, tmp=tmp_path)
    res = _run(after, tmp_path / "out", clip=media["truth_a"], before=before,
               notes={"vendor": "TestVendor", "model": "T-1", "disk": "generated 1 MB", "scenario": "wiped index"})
    v = res["verdict"]
    assert v["code"] == "MATCHES", v
    c = res["combined"]
    assert c["frame_recall_pct"] == c["frame_precision_pct"] == c["in_order_pct"] == 100.0
    assert res["placement"]["placement_precision_pct"] == 100.0 and res["placement"]["byte_recall_pct"] >= 85
    assert res["evidence_unchanged"] is True
    assert res["detection"]["brand"] and res["segments"][0]["ffprobe_valid"] is True
    assert res["segments"][0]["status"] in ("PARTIAL", "UNCERTAIN")                 # never COMPLETE by carving
    assert res["not_measured"] == ["time/camera: no recording log was supplied"]     # everything else was measured


def test_extra_recordings_on_the_disk_lower_precision_not_recall(media, tmp_path):
    before, after = _disks(media, both=True, tmp=tmp_path)
    res = _run(after, tmp_path / "out", clip=media["truth_a"], before=before)
    c = res["combined"]
    assert c["frame_recall_pct"] >= 99.0 and c["frame_precision_pct"] < 99.0
    assert res["verdict"]["code"] == "COMPLETE_WITH_EXTRAS"


def test_a_different_clip_gives_no_match(media, tmp_path):
    _, after = _disks(media, both=False, tmp=tmp_path)
    res = _run(after, tmp_path / "out", clip=media["truth_other"])
    assert res["verdict"]["code"] == "NO_MATCH" and res["combined"]["frame_recall_pct"] == 0.0


def test_without_a_clip_accuracy_is_explicitly_not_measured(media, tmp_path):
    _, after = _disks(media, both=False, tmp=tmp_path)
    res = _run(after, tmp_path / "out")
    assert res["verdict"]["code"] == "NOT_MEASURED" and "combined" not in res
    assert any("no ground-truth clip" in x for x in res["not_measured"])
    assert any("no before-deletion image" in x for x in res["not_measured"])
    assert "%" not in res["verdict"]["headline"]                                     # no percentage without ground truth


def test_unrecognisable_image_reports_no_video(tmp_path):
    noise = tmp_path / "noise.dd"
    noise.write_bytes(bytes(range(256)) * 400)
    res = _run(noise, tmp_path / "out")
    assert res["verdict"]["code"] == "NO_VIDEO" and res["segments"] == []


def test_log_is_compared_when_supplied(media, tmp_path):
    _, after = _disks(media, both=False, tmp=tmp_path)
    log = [{"name": "test recording", "start": "2025-05-01T09:00:00Z", "end": "2025-05-01T09:00:02Z"}]
    res = _run(after, tmp_path / "out", clip=media["truth_a"], log_entries=log)
    assert res["log"]["entries"][0]["time_coverage_pct"] is not None


def test_reports_are_written_and_readable(media, tmp_path):
    before, after = _disks(media, both=False, tmp=tmp_path)
    out = tmp_path / "out"
    res = _run(after, out, clip=media["truth_a"], before=before,
               notes={"vendor": "TestVendor", "model": "T-1", "scenario": "wiped index"})
    paths = K.write_outputs(res, out)
    md = paths["markdown"].read_text(encoding="utf-8")
    assert "# Recorder Validation Report" in md and "The recovered video matches" in md
    assert "Row for docs/VALIDATION_REPORT.md" in md and "TestVendor / T-1" in md
    assert res["inputs"]["after_image"]["sha256_before"] in md                       # integrity table
    assert paths["pdf"].read_bytes()[:4] == b"%PDF"
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["verdict"]["code"] == "MATCHES" and data["kit_version"] == K.KIT_VERSION
    assert (out / "exports").is_dir() and any((out / "exports").glob("*.mp4"))


def test_evidence_is_never_modified(media, tmp_path):
    before, after = _disks(media, both=False, tmp=tmp_path)
    import hashlib
    h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    hb, ha = h(before), h(after)
    _run(after, tmp_path / "out", clip=media["truth_a"], before=before)
    assert h(before) == hb and h(after) == ha


def test_a_changed_evidence_image_is_flagged_and_exit_code_3(media, tmp_path, monkeypatch, capsys):
    before, after = _disks(media, both=False, tmp=tmp_path)
    from backend.acquisition import EvidenceImage
    monkeypatch.setattr(EvidenceImage, "verify_unchanged", lambda self, progress_cb=None: False)
    code = K.main(["--after", str(after), "--clip", str(media["truth_a"]), "--out", str(tmp_path / "out")])
    assert code == 3
    assert "EVIDENCE_CHANGED" in (tmp_path / "out" / "results.json").read_text() or "STOP" in capsys.readouterr().out


def test_bad_input_is_reported_with_exit_code_2(media, tmp_path, capsys):
    before, after = _disks(media, both=False, tmp=tmp_path)
    assert K.main(["--after", str(tmp_path / "missing.dd"), "--out", str(tmp_path / "o1")]) == 2
    assert K.main(["--after", str(after), "--before", str(after), "--out", str(tmp_path / "o2")]) == 2
    assert K.main(["--after", str(after), "--clip", str(tmp_path / "nope.mp4"), "--out", str(tmp_path / "o3")]) == 2
    bad = tmp_path / "notes.json"; bad.write_text("{not json")
    assert K.main(["--after", str(after), "--notes", str(bad), "--out", str(tmp_path / "o4")]) == 2
    assert "Input problem" in capsys.readouterr().err


def test_command_line_end_to_end(media, tmp_path, capsys):
    before, after = _disks(media, both=False, tmp=tmp_path)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"vendor": "TestVendor", "model": "T-1"}))
    code = K.main(["--after", str(after), "--before", str(before), "--clip", str(media["truth_a"]),
                   "--notes", str(notes), "--out", str(tmp_path / "run")])
    out = capsys.readouterr().out
    assert code == 0 and "VERDICT: The recovered video matches" in out
    assert (tmp_path / "run" / "validation_report.pdf").is_file()


def test_pipeline_agrees_with_the_application_scan(media, tmp_path, auth_client):
    """The kit must make the same decisions as the web app on the same image."""
    _, after = _disks(media, both=True, tmp=tmp_path)
    cid = auth_client.post("/api/cases", json={"case_number": "KIT-PARITY-1", "examiner": "Test Inspector"}).json()["case_id"]
    auth_client.post(f"/api/cases/{cid}/evidence", json={"path": str(after)})
    assert auth_client.post(f"/api/cases/{cid}/scan").status_code == 200
    import time
    for _ in range(100):
        segs = auth_client.get(f"/api/cases/{cid}/segments").json()
        if segs:
            break
        time.sleep(0.2)
    from backend.acquisition import EvidenceImage
    from backend.pipeline import recover
    with EvidenceImage.open(after) as img:
        r = recover(img, "x")
    assert len(r.segments) == len(segs)
    assert sorted((s.camera, s.frame_count, s.status.value) for s in r.segments) == \
           sorted((s["camera"], s["frame_count"], s["status"]) for s in segs)
