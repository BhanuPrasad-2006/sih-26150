"""Tests for backend/imaging.py — read-only acquisition of a source into a raw image."""

import hashlib
import io
import os
import time
from pathlib import Path

import pytest

from backend import imaging
from backend.acquisition import AcquisitionError, EvidenceImage


def _make_source(tmp_path: Path, size: int = 3 * 1024 * 1024 + 777) -> Path:
    src = tmp_path / "source.bin"
    src.write_bytes(os.urandom(size))
    return src


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FlakyFile(io.RawIOBase):
    """Wraps a real file; any read that overlaps a bad byte range raises OSError, like a failing sector."""

    def __init__(self, path, bad: list[tuple[int, int]]):
        self._f = open(path, "rb", buffering=0)
        self._bad = bad
        self._pos = 0

    def seek(self, pos, whence=0):
        self._pos = self._f.seek(pos, whence)
        return self._pos

    def read(self, n=-1):
        start = self._pos
        end = start + (n if n >= 0 else 1 << 62)
        for b0, bl in self._bad:
            if start < b0 + bl and end > b0:
                raise OSError(5, "simulated I/O error")
        data = self._f.read(n)
        self._pos += len(data)
        return data

    def readable(self):
        return True

    def close(self):
        self._f.close()
        super().close()


def test_image_is_bit_exact_and_hashes_match(tmp_path):
    src = _make_source(tmp_path)
    dst = tmp_path / "out.dd"
    rep = imaging.acquire_image(src, dst, write_blocker_attested=True)

    assert dst.read_bytes() == src.read_bytes()
    assert rep.bytes_written == src.stat().st_size
    assert rep.sha256 == _sha(src) == _sha(dst)
    assert rep.md5 == hashlib.md5(src.read_bytes()).hexdigest()
    assert rep.dest_hash_verified and rep.is_bit_exact and not rep.bad_ranges
    sidecar = Path(str(dst) + ".acquisition.json")
    assert sidecar.is_file() and rep.sha256 in sidecar.read_text()


def test_source_is_never_modified(tmp_path):
    src = _make_source(tmp_path)
    before, mtime = _sha(src), src.stat().st_mtime_ns
    imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True, verify_source=True)
    assert _sha(src) == before and src.stat().st_mtime_ns == mtime


def test_source_rehash_verified(tmp_path):
    src = _make_source(tmp_path)
    rep = imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True, verify_source=True)
    assert rep.source_rehash_verified is True


def test_result_opens_as_evidence_with_same_hash(tmp_path):
    src = _make_source(tmp_path)
    rep = imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True)
    with EvidenceImage.open(tmp_path / "out.dd") as img:
        assert img.sha256_before == rep.sha256 and img.md5_before == rep.md5


def test_refuses_without_write_blocker_attestation(tmp_path):
    src = _make_source(tmp_path, 4096)
    with pytest.raises(AcquisitionError, match="[Ww]rite-blocker"):
        imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=False)
    assert not (tmp_path / "out.dd").exists()


def test_refuses_to_overwrite_existing_destination(tmp_path):
    src = _make_source(tmp_path, 4096)
    dst = tmp_path / "out.dd"
    dst.write_bytes(b"precious")
    with pytest.raises(AcquisitionError, match="already exists"):
        imaging.acquire_image(src, dst, write_blocker_attested=True)
    assert dst.read_bytes() == b"precious"


def test_refuses_device_destination_and_missing_source(tmp_path):
    src = _make_source(tmp_path, 4096)
    with pytest.raises(AcquisitionError, match="device"):
        imaging.acquire_image(src, r"\\.\PhysicalDrive9", write_blocker_attested=True)
    with pytest.raises(AcquisitionError, match="not found"):
        imaging.acquire_image(tmp_path / "nope.bin", tmp_path / "o.dd", write_blocker_attested=True)
    with pytest.raises(AcquisitionError, match="folder"):
        imaging.acquire_image(src, tmp_path / "no_such_dir" / "o.dd", write_blocker_attested=True)


def test_bad_sectors_are_zero_filled_and_reported(tmp_path):
    src = _make_source(tmp_path)
    bad = [(1024 * 1024 + 512, 1024)]                       # two adjacent sectors inside the 2nd chunk
    rep = imaging.acquire_image(
        src, tmp_path / "out.dd", write_blocker_attested=True,
        _opener=lambda p, mode, buffering=0: FlakyFile(p, bad),
    )
    out, orig = (tmp_path / "out.dd").read_bytes(), src.read_bytes()

    assert rep.bad_ranges == [(1024 * 1024 + 512, 1024)]
    assert rep.bad_bytes == 1024
    assert out[1024 * 1024 + 512: 1024 * 1024 + 1536] == b"\x00" * 1024
    assert out[: 1024 * 1024 + 512] == orig[: 1024 * 1024 + 512]
    assert out[1024 * 1024 + 1536:] == orig[1024 * 1024 + 1536:]
    assert len(out) == len(orig)
    assert rep.dest_hash_verified is True
    assert rep.is_bit_exact is False                          # honest: not bit-exact in those ranges
    assert any("not bit-exact" in n for n in rep.notes)


def test_max_bytes_stops_early(tmp_path):
    src = _make_source(tmp_path)
    rep = imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True, max_bytes=1_500_000)
    assert rep.bytes_written == 1_500_000 and rep.stopped_early is True
    assert (tmp_path / "out.dd").read_bytes() == src.read_bytes()[:1_500_000]


def test_progress_callback_reports_bytes(tmp_path):
    src = _make_source(tmp_path)
    seen = []
    imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True,
                          progress_cb=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1] == (src.stat().st_size, src.stat().st_size)


def test_crash_mid_copy_leaves_no_partial_image(tmp_path):
    src = _make_source(tmp_path)

    class Boom(FlakyFile):
        def read(self, n=-1):
            if self._pos >= 1024 * 1024:
                raise RuntimeError("boom")
            return super().read(n)

    with pytest.raises(RuntimeError):
        imaging.acquire_image(src, tmp_path / "out.dd", write_blocker_attested=True,
                              _opener=lambda p, mode, buffering=0: Boom(p, []))
    assert not (tmp_path / "out.dd").exists()


def test_device_path_detection():
    assert imaging.is_device_path(r"\\.\PhysicalDrive1")
    assert imaging.is_device_path("/dev/sdb")
    assert not imaging.is_device_path(r"C:\cases\x.dd")


def test_list_local_drives_never_raises():
    drives = imaging.list_local_drives()
    assert isinstance(drives, list)
    for d in drives:
        assert "path" in d


# ── API ───────────────────────────────────────────────────────────────────────

def _make_case(client, number):
    r = client.post("/api/cases", json={"case_number": number, "examiner": "Test Inspector"})
    assert r.status_code == 200
    return r.json()["case_id"]


def test_api_acquire_disabled_by_default(auth_client, tmp_path, monkeypatch):
    monkeypatch.delenv("FORENSIC_ALLOW_LOCAL_ACQUISITION", raising=False)
    cid = _make_case(auth_client, "ACQ-OFF-1")
    r = auth_client.post(f"/api/cases/{cid}/acquire", json={"source_path": str(_make_source(tmp_path, 4096)),
                                                            "write_blocker_confirmed": True})
    assert r.status_code == 403
    d = auth_client.get("/api/acquisition/drives").json()
    assert d["enabled"] is False and d["drives"] == []


def test_api_acquire_end_to_end_then_scan(auth_client, tmp_path, monkeypatch):
    monkeypatch.setenv("FORENSIC_ALLOW_LOCAL_ACQUISITION", "1")
    src = _make_source(tmp_path, 300_000)
    cid = _make_case(auth_client, "ACQ-ON-1")

    # attestation is mandatory
    r = auth_client.post(f"/api/cases/{cid}/acquire", json={"source_path": str(src)})
    assert r.status_code == 400

    r = auth_client.post(f"/api/cases/{cid}/acquire", json={"source_path": str(src), "write_blocker_confirmed": True})
    assert r.status_code == 200
    for _ in range(100):
        st = auth_client.get(f"/api/cases/{cid}/acquire/status").json()
        if st["state"] != "running":
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    assert st["report"]["sha256"] == _sha(src) and st["report"]["dest_hash_verified"] is True

    detail = auth_client.get(f"/api/cases/{cid}").json()
    assert any(a["action"] == "acquisition_completed" and st["report"]["sha256"] in a["details"]
               for a in detail["audit"])
    assert detail["evidence"][-1]["sha256_before"] == st["report"]["sha256"]
    assert auth_client.post(f"/api/cases/{cid}/scan").status_code == 200


def test_api_acquire_failure_is_reported(auth_client, tmp_path, monkeypatch):
    monkeypatch.setenv("FORENSIC_ALLOW_LOCAL_ACQUISITION", "1")
    cid = _make_case(auth_client, "ACQ-BAD-1")
    r = auth_client.post(f"/api/cases/{cid}/acquire",
                         json={"source_path": str(tmp_path / "missing.bin"), "write_blocker_confirmed": True})
    assert r.status_code == 200
    for _ in range(100):
        st = auth_client.get(f"/api/cases/{cid}/acquire/status").json()
        if st["state"] != "running":
            break
        time.sleep(0.1)
    assert st["state"] == "failed" and "not found" in st["error"].lower()
