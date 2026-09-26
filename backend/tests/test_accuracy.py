"""
test_accuracy.py — measurement of recovery against supplied ground truth (backend/accuracy.py).

Frame tests use real ffmpeg-encoded video. The placement test builds a real fragmented DHFS 4.1 disk,
"deletes" it by wiping the descriptor table, carves it, and measures against the ORIGINAL disk's index.
"""

import json
import os
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import accuracy
from backend.acquisition import EvidenceImage
from backend.exporter import ffmpeg_available, ffprobe_available
from backend.plugins.constants import DHFS_DESC_SIZE
from backend.plugins.dahua import DahuaPlugin
from backend.reconstructor import label_all

_NEED_FFMPEG = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)


# ── frame matching (pure logic) ───────────────────────────────────────────────

def test_identical_sequences_are_100_percent():
    r = accuracy.match_frame_sequences(list("abcdef"), list("abcdef"))
    assert (r["frame_recall_pct"], r["frame_precision_pct"], r["in_order_pct"]) == (100.0, 100.0, 100.0)
    assert r["missing_ranges"] == []


def test_truncated_recovery_reports_missing_range():
    r = accuracy.match_frame_sequences(list("abcdefghij"), list("abcdefg"))
    assert r["frame_recall_pct"] == 70.0 and r["frame_precision_pct"] == 100.0
    assert r["missing_ranges"] == [[7, 9]] and r["missing_frames"] == 3 and r["extra_or_wrong_frames"] == 0


def test_extra_and_wrong_frames_lower_precision_not_recall():
    r = accuracy.match_frame_sequences(list("abcd"), ["a", "b", "X", "Y", "c", "d"])
    assert r["frame_recall_pct"] == 100.0
    assert r["frame_precision_pct"] == pytest.approx(66.67, abs=0.01)
    assert r["extra_or_wrong_frames"] == 2


def test_reordered_fragments_are_matched_but_flagged_out_of_order():
    truth = list("abcdefghij")
    recovered = list("fghij") + list("abcde")           # two halves swapped
    r = accuracy.match_frame_sequences(truth, recovered)
    assert r["frame_recall_pct"] == 100.0
    assert r["in_order_pct"] == 50.0                     # only one half can be in order


def test_duplicate_frames_are_not_double_counted():
    r = accuracy.match_frame_sequences(["a", "a", "b"], ["a", "b"])
    assert r["matched_frames"] == 2 and r["frame_recall_pct"] == pytest.approx(66.67, abs=0.01)
    r2 = accuracy.match_frame_sequences(["a", "b"], ["a", "a", "a", "b"])       # the same frame repeated is not credit
    assert r2["matched_frames"] == 2 and r2["extra_or_wrong_frames"] == 2


def test_perceptual_matching_tolerates_small_hash_differences():
    truth = [0b1010101010101010, 0xFFFF0000FFFF0000, 0x0123456789ABCDEF]
    noisy = [truth[0] ^ 0b11, truth[1] ^ 0b1, truth[2] ^ (1 << 40)]              # 1-2 bit flips
    assert accuracy.match_frame_sequences(truth, noisy, max_distance=6)["frame_recall_pct"] == 100.0
    assert accuracy.match_frame_sequences(truth, noisy, max_distance=0)["frame_recall_pct"] == 0.0


def test_empty_truth_gives_no_percentage_instead_of_a_guess():
    r = accuracy.match_frame_sequences([], list("abc"))
    assert r["frame_recall_pct"] is None


# ── bytes ─────────────────────────────────────────────────────────────────────

def test_compare_bytes_identical_and_first_mismatch(temp_dir):
    a, b, c = (Path(temp_dir) / n for n in ("a", "b", "c"))
    a.write_bytes(b"0123456789" * 100)
    b.write_bytes(b"0123456789" * 100)
    data = bytearray(b"0123456789" * 100)
    data[437] ^= 0xFF
    c.write_bytes(bytes(data))
    assert accuracy.compare_bytes(a, b)["identical"] is True
    r = accuracy.compare_bytes(a, c)
    assert r["identical"] is False and r["first_mismatch_offset"] == 437
    assert r["positional_match_pct"] == pytest.approx(99.9, abs=0.01)


def test_compare_bytes_length_difference(temp_dir):
    a, b = Path(temp_dir) / "a", Path(temp_dir) / "b"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"x" * 60)
    r = accuracy.compare_bytes(a, b)
    assert r["identical"] is False and r["first_mismatch_offset"] == 60


# ── real video ────────────────────────────────────────────────────────────────

def _mp4(path, source="testsrc", seconds=3, crf=None):
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=duration={seconds}:size=320x240:rate=10",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p"]
    if crf is not None:
        args += ["-crf", str(crf)]
    subprocess.run(args + [str(path)], check=True)
    return Path(path)


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("acc")
    full = _mp4(d / "full.mp4")
    trunc = d / "trunc.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(full), "-c", "copy", "-frames:v", "20", str(trunc)], check=True)
    other = _mp4(d / "other.mp4", source="smptebars")
    hq = _mp4(d / "hq.mp4", crf=12)
    lq = _mp4(d / "lq.mp4", crf=40)
    return SimpleNamespace(full=full, trunc=trunc, other=other, hq=hq, lq=lq)


@_NEED_FFMPEG
def test_real_video_identical_truncated_and_different(videos):
    same = accuracy.compare_frames(videos.full, videos.full)
    assert same["truth_frames"] == 30 and same["frame_recall_pct"] == 100.0 and same["in_order_pct"] == 100.0

    part = accuracy.compare_frames(videos.trunc, videos.full)            # only the first 20 of 30 frames recovered
    assert part["matched_frames"] == 20
    assert part["frame_recall_pct"] == pytest.approx(66.67, abs=0.01) and part["frame_precision_pct"] == 100.0
    assert part["missing_ranges"] == [[20, 29]]

    diff = accuracy.compare_frames(videos.other, videos.full)
    assert diff["frame_recall_pct"] == 0.0


@_NEED_FFMPEG
def test_reencoded_truth_fails_exact_but_passes_perceptual(videos):
    exact = accuracy.compare_frames(videos.lq, videos.hq, mode="exact")
    assert exact["frame_recall_pct"] < 10                                 # different encode: pixels differ
    perc = accuracy.compare_frames(videos.lq, videos.hq, mode="perceptual")
    assert perc["frame_recall_pct"] >= 85
    assert "upper bound" in perc["meaning"]


# ── log ───────────────────────────────────────────────────────────────────────

def _seg(cam, start, end, sid="s"):
    return SimpleNamespace(segment_id=sid, camera=cam, start_time=start, end_time=end)


def _t(h, m=0, s=0):
    return datetime(2026, 3, 1, h, m, s, tzinfo=timezone.utc)


def test_log_time_coverage_and_deltas():
    segs = [_seg(1, _t(10, 0, 30), _t(10, 30), "a"), _seg(1, _t(10, 40), _t(11, 0), "b"), _seg(2, _t(10), _t(11), "c")]
    log_ = [{"name": "cam1 hour", "camera": 1, "start": "2026-03-01T10:00:00Z", "end": "2026-03-01T11:00:00Z"},
            {"name": "cam3 nothing", "camera": 3, "start": "2026-03-01T10:00:00Z", "end": "2026-03-01T11:00:00Z"}]
    r = accuracy.compare_to_log(segs, log_)["entries"]
    assert r[0]["covered_seconds"] == 30 * 60 - 30 + 20 * 60
    assert r[0]["time_coverage_pct"] == 82.5                       # 2970 s of 3600 s
    assert r[0]["matching_segments"] == 2 and r[0]["start_delta_seconds"] == 30.0
    assert r[1]["time_coverage_pct"] == 0.0 and r[1]["matching_segments"] == 0


def test_log_utc_needs_a_device_offset_and_applies_it():
    seg = [_seg(1, _t(15, 30), _t(16, 30))]                 # device clock reads 15:30-16:30 (UTC+5:30)
    entry = [{"camera": 1, "start": "2026-03-01T10:00:00Z", "end": "2026-03-01T11:00:00Z"}]
    with pytest.raises(ValueError):
        accuracy.compare_to_log(seg, entry, None, "utc")
    r = accuracy.compare_to_log(seg, entry, 330, "utc")["entries"][0]
    assert r["time_coverage_pct"] == 100.0 and r["start_delta_seconds"] == 0.0
    assert accuracy.compare_to_log(seg, entry, 330, "device")["entries"][0]["time_coverage_pct"] == 0.0


# ── placement ────────────────────────────────────────────────────────────────

def test_placement_numbers_are_exact():
    ref = {"R1": [(0, 100)], "R2": [(200, 300)]}
    rec = {"S1": [(0, 100)], "S2": [(200, 250), (400, 450)]}       # all of R1, half of R2, 50 bytes of nothing
    r = accuracy.placement_report(ref, rec, "test reference")
    assert r["original_bytes"] == 200 and r["recovered_bytes"] == 200
    assert r["recovered_bytes_at_original_locations"] == 150
    assert r["byte_recall_pct"] == 75.0 and r["placement_precision_pct"] == 75.0
    by = {x["original"]: x for x in r["per_original"]}
    assert by["R1"]["byte_recall_pct"] == 100.0 and by["R2"]["byte_recall_pct"] == 50.0
    seg = {x["segment"]: x for x in r["per_segment"]}
    assert seg["S2"]["placed_pct"] == 50.0 and seg["S2"]["dominant_original"] == "R2"


def test_placement_flags_a_segment_that_mixes_two_originals():
    ref = {"R1": [(0, 100)], "R2": [(100, 200)]}
    r = accuracy.placement_report(ref, {"S": [(50, 150)]}, "test")
    assert r["per_segment"][0]["mixes_several_originals"] is True


# ── real fragmented DHFS disk: delete it, carve, measure against the original ─

@_NEED_FFMPEG
def test_deleted_dhfs_disk_measured_against_the_original_index(temp_dir):
    from backend.tests import test_dahua_dhfs as T

    d = Path(temp_dir)
    base = int(datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    a = T._dhav_stream(T._encode("testsrc", str(d / "a.h264")), 0, base)
    b = T._dhav_stream(T._encode("smptebars", str(d / "b.h264")), 1, base + 3)
    na, nb = -(-len(a) // T._CL), -(-len(b) // T._CL)

    def wipe(disk: bytes) -> bytes:
        """Simulate deletion: every descriptor becomes 'free'; the cluster data stays."""
        m = bytearray(disk)
        dt = T._DESC_SECTOR * 512
        for i in range(T._N_DESC):
            m[dt + i * DHFS_DESC_SIZE : dt + (i + 1) * DHFS_DESC_SIZE] = b"\xfe" + b"\x00" * (DHFS_DESC_SIZE - 1)
        return bytes(m)

    results = {}
    layouts = {
        "contiguous": [dict(camera=1, data=a, clusters=list(range(2, 2 + na)), t0=0),
                       dict(camera=2, data=b, clusters=list(range(2 + na, 2 + na + nb)), t0=3)],
        "interleaved": [dict(camera=1, data=a, clusters=[2 * i + 2 for i in range(na)], t0=0),
                        dict(camera=2, data=b, clusters=[2 * i + 3 for i in range(nb)], t0=3)],
    }
    for name, recs in layouts.items():
        original = d / f"orig_{name}.dd"
        deleted = d / f"del_{name}.dd"
        disk = T.build_dhfs_disk(recs)
        original.write_bytes(disk)
        deleted.write_bytes(wipe(disk))

        with EvidenceImage.open(str(deleted)) as img:
            plugin = DahuaPlugin()
            assert plugin.list_recordings(img)[0] == []                  # index really is gone
            frames, _ = plugin.carve(img)
            segs = label_all(frames, "ev")

        ref, source = accuracy.reference_ranges_from_original(str(original))
        assert "DHFS 4.1 index" in source and len(ref) == 2
        rec = {s.segment_id: [(o.start, o.end) for o in s.disk_offsets] for s in segs}
        results[name] = accuracy.placement_report(ref, rec, source)

    c, i = results["contiguous"], results["interleaved"]
    assert c["placement_precision_pct"] == 100.0 and i["placement_precision_pct"] == 100.0   # nothing recovered from the wrong place
    assert c["byte_recall_pct"] >= 90.0                                                      # only the 512-byte DHII sectors are not video
    # Frames split across another camera's clusters used to be lost (interleaved < contiguous). They are now stitched back
    # from their trailer and continuation, so interleaving costs nothing here (see test_dahua_stitch.py).
    assert i["byte_recall_pct"] >= c["byte_recall_pct"] - 0.01
    assert 0 < i["byte_recall_pct"]


# ── API ───────────────────────────────────────────────────────────────────────

@_NEED_FFMPEG
def test_accuracy_endpoint_end_to_end_and_report(auth_client, temp_dir):
    d = Path(temp_dir)
    raw = d / "clip.h264"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", str(raw)], check=True)
    stream = raw.read_bytes()
    disk = d / "unknown_recorder.dd"
    disk.write_bytes(b"\xCC" * 8192 + stream + b"\xCC" * 8192)             # no brand marker -> generic carving
    truth_ok = d / "truth.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "h264", "-i", str(raw), "-c", "copy", str(truth_ok)], check=True)
    truth_bad = _mp4(d / "wrong.mp4", source="smptebars", seconds=2)

    case_id = auth_client.post("/api/cases", json={"case_number": "ACC-001", "examiner": "Test Inspector", "notes": ""}).json()["case_id"]
    auth_client.post(f"/api/cases/{case_id}/evidence", json={"path": str(disk)})
    auth_client.post(f"/api/cases/{case_id}/scan")
    import time
    segs = []
    for _ in range(100):
        segs = auth_client.get(f"/api/cases/{case_id}/segments").json()
        if segs:
            break
        time.sleep(0.1)
    assert len(segs) == 1
    sid = segs[0]["segment_id"]

    # not exported yet: frames/bytes cannot be measured, and the answer says so
    r0 = auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": sid},
                          files={"ground_truth": ("truth.mp4", truth_ok.read_bytes())})
    assert r0.status_code == 200
    assert any("not been exported" in m for m in r0.json()["not_measured"]) and "frames" not in r0.json()

    assert auth_client.post(f"/api/cases/{case_id}/export/{sid}").status_code == 200

    ok = auth_client.post(f"/api/cases/{case_id}/accuracy",
                          data={"segment_id": sid, "original_image_path": str(disk)},
                          files={"ground_truth": ("truth.mp4", truth_ok.read_bytes())}).json()
    assert ok["frames"]["frame_recall_pct"] == 100.0 and ok["frames"]["frame_precision_pct"] == 100.0
    assert ok["frames"]["in_order_pct"] == 100.0
    assert ok["placement"]["byte_recall_pct"] == 100.0
    assert "generic stream carving" in ok["placement"]["reference_source"]        # says what the reference is
    assert "time/camera: no recording log was supplied" in ok["not_measured"]
    assert set(ok["measured"]) == {"bytes", "frames", "placement"}

    bad = auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": sid},
                           files={"ground_truth": ("wrong.mp4", truth_bad.read_bytes())}).json()
    assert bad["frames"]["frame_recall_pct"] == 0.0

    log_ = json.dumps({"recordings": [{"name": "x", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"}]})
    lg = auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": sid},
                          files={"truth_log": ("log.json", log_.encode())}).json()
    assert lg["log"]["entries"][0]["time_coverage_pct"] == 0.0                    # segment has no times: 0, not a guess

    listed = auth_client.get(f"/api/cases/{case_id}/accuracy").json()
    assert len(listed) == 4

    audit = auth_client.get(f"/api/cases/{case_id}/audit").json()
    assert audit["chain_intact"] is True
    assert any(e["action"] == "accuracy_check" for e in audit["entries"])

    rep = auth_client.get(f"/api/cases/{case_id}/report")
    assert rep.status_code == 200 and rep.content[:4] == b"%PDF"


def test_accuracy_endpoint_validation(auth_client, temp_dir):
    case_id = auth_client.post("/api/cases", json={"case_number": "ACC-VAL", "examiner": "Test Inspector", "notes": ""}).json()["case_id"]
    # no evidence yet
    assert auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": "x", "original_image_path": "C:/nope"}).status_code == 400
    # no ground truth at all
    assert auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": "x"}).status_code == 400
    assert auth_client.post(f"/api/cases/{case_id}/accuracy", data={"segment_id": "x", "mode": "bogus", "original_image_path": "x"}).status_code == 400
    assert auth_client.get("/api/cases/does-not-exist/accuracy").status_code == 404


# ── PDF report section ───────────────────────────────────────────────────────

def test_report_section_says_not_measured_without_ground_truth():
    from backend import reporting

    S = reporting._styles()
    flow = reporting._accuracy_section([], S)
    text = " ".join(getattr(f, "text", "") for f in flow)
    assert "NOT MEASURED" in text and "%" not in text          # no percentage may appear without ground truth


def test_report_section_lists_measured_values_and_reference():
    from backend import reporting
    from reportlab.platypus import Table

    result = {
        "segment_id": "abcdef12-0000", "not_measured": ["time/camera: no recording log was supplied"],
        "frames": {"frame_recall_pct": 93.0, "frame_precision_pct": 100.0, "in_order_pct": 100.0},
        "bytes": {"identical": False},
        "placement": {"byte_recall_pct": 88.5, "reference_source": "the ORIGINAL disk's own DHFS 4.1 index"},
    }
    flow = reporting._accuracy_section([result], reporting._styles())
    tables = [f for f in flow if isinstance(f, Table)]
    assert len(tables) == 1
    cells = [str(c) for row in tables[0]._cellvalues for c in row]
    assert "93.0%" in cells and "88.5%" in cells and "NO" in cells
    assert any("DHFS 4.1 index" in getattr(f, "text", "") for f in flow)
