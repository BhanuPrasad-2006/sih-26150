"""
test_dahua_dhfs.py — Dahua DHFS 4.1 disk index (Wullen 2025 spec; Batista's extractor agrees).

Known-answer tests use values printed in the spec's hex-dump figures. The synthetic disk
interleaves two recordings cluster-by-cluster (real fragmentation) and carries real H.264 inside
real DHAV frames, so reassembly, camera numbers, times, export and decoding are all exercised.
"""

import mmap
import os
import struct
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.models import SegmentStatus
from backend.plugins.constants import (
    DHFS_BOOT_OFF_BEGIN,
    DHFS_BOOT_OFF_DESC_COUNT,
    DHFS_BOOT_OFF_DESC_TABLE,
    DHFS_BOOT_OFF_END,
    DHFS_BOOT_OFF_SECTOR_SIZE,
    DHFS_BOOT_OFF_SECTORS_PER_CLUSTER,
    DHFS_BOOT_OFF_VIDEO_AREA,
    DHFS_DESC_SIZE,
    DHFS_PART_END_MAGIC,
    DHFS_PART_ENTRIES_START,
    DHFS_PART_ENTRY_SIZE,
    DHFS_PART_OFF_BOOT,
    DHFS_PART_OFF_LENGTH,
    DHFS_PART_OFF_START,
    DHFS_PART_TABLE_OFFSET,
    DHFS_SIGNATURE,
)
from backend.plugins.dahua import DahuaPlugin
from backend.plugins.dahua_dhfs import decode_dhfs_time, iter_recordings, read_partition, read_partition_table, read_partitions
from backend.plugins.stream_carver import _carve_annexb_run
from backend.reconstructor import label_all
from backend.test_images.gen_test_image import _encode_dhav_date, make_dhav_frame

_NEED_FFMPEG = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)


class _Mem:
    """Minimal mmap stand-in over bytes."""
    def __init__(self, b): self.b = b
    def __getitem__(self, k): return self.b[k]
    def __len__(self): return len(self.b)


# ── Known answers from Wullen's figures ───────────────────────────────────────

def test_timestamp_layout_reproduces_the_specs_worked_example():
    # Spec: "0x76A31851 LE ... corresponds to 12.04.2020 10:13:54" — the boot sector figure shows
    # these bytes as 76 A3 18 51, i.e. the little-endian value 0x5118A376.
    assert decode_dhfs_time(0x5118A376) == datetime(2020, 4, 12, 10, 13, 54, tzinfo=timezone.utc)


def test_spec_boot_sector_sample_parses_to_the_printed_values():
    """Fig. 3: descriptor table at sector 187, video area at sector 6656, 29807 descriptors, 512 B/sector, 4096 sectors/cluster."""
    bs = bytearray(0x150)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_BEGIN, 0x511D60B9)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_END, 0x511EB4C1)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_SECTOR_SIZE, 512)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_SECTORS_PER_CLUSTER, 4096)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_DESC_TABLE, 187)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_VIDEO_AREA, 6656)
    struct.pack_into("<I", bs, DHFS_BOOT_OFF_DESC_COUNT, 29807)
    disk = bytearray(6656 * 512 + 4096)
    disk[34 * 512 : 34 * 512 + len(bs)] = bs
    part = read_partition(_Mem(bytes(disk)), len(disk), 0, (34, 0, 122099292))
    assert part is not None
    assert part.sector_size == 512 and part.cluster_size == 4096 * 512
    assert part.desc_table == 187 * 512 and part.video_area == 6656 * 512
    assert part.desc_count == 29807
    assert part.begin == datetime(2020, 4, 14, 22, 2, 57, tzinfo=timezone.utc)
    # The spec's own numbers fit together: 29807 clusters of 4096 sectors fill the partition (122,099,292 sectors).
    assert abs((6656 + 29807 * 4096) - 122099292) < 4096


def test_spec_partition_table_sample_and_magic():
    """Fig. 2: four partitions at sectors 0 / 0x07480000 / 0x0E8F0000 / 0x15D60000, boot sector at sector 34, AA55AA55 end marker."""
    disk = bytearray(DHFS_PART_TABLE_OFFSET + 0x200)
    disk[: len(DHFS_SIGNATURE)] = DHFS_SIGNATURE
    starts = [0, 0x07480000, 0x0E8F0000, 0x15D60000]
    lengths = [0x0747165C, 0x07462CB8, 0x07464314, 0x07465970]
    pos = DHFS_PART_TABLE_OFFSET + DHFS_PART_ENTRIES_START
    for s, ln in zip(starts, lengths):
        struct.pack_into("<I", disk, pos + DHFS_PART_OFF_BOOT, 34)
        struct.pack_into("<Q", disk, pos + DHFS_PART_OFF_START, s)
        struct.pack_into("<I", disk, pos + DHFS_PART_OFF_LENGTH, ln)
        pos += DHFS_PART_ENTRY_SIZE
    disk[pos : pos + 4] = DHFS_PART_END_MAGIC
    assert pos == 0x3D34                                   # where the spec figure shows the magic (15664 + 4)
    assert read_partition_table(_Mem(bytes(disk)), len(disk)) == list(zip([34] * 4, starts, lengths))


def test_not_dhfs_gives_no_partitions():
    data = os.urandom(0x5000)
    assert read_partition_table(_Mem(data), len(data)) == []


def test_spec_main_descriptor_sample_arithmetic():
    """Fig. 5 main descriptor: its printed video ID equals its own index when the table starts at sector 187."""
    main = bytes.fromhex("01234803" "B9601D51" "00701D51" "42100000" "000E0000" "00000000" "40100000" "00000000")
    assert len(main) == DHFS_DESC_SIZE
    assert (228864 - 187 * 512) // DHFS_DESC_SIZE == struct.unpack_from("<I", main, 24)[0] == 0x1040
    assert (main[1] & 0x0F) + 1 == 4                       # spec: 0x23 -> camera 4
    assert struct.unpack_from("<I", main, 12)[0] == 0x1042  # next descriptor
    assert struct.unpack_from("<I", main, 16)[0] == 0x0E00  # size of the last fragment, sectors
    begin = decode_dhfs_time(struct.unpack_from("<I", main, 4)[0])
    end = decode_dhfs_time(struct.unpack_from("<I", main, 8)[0])
    assert begin == datetime(2020, 4, 14, 22, 2, 57, tzinfo=timezone.utc)
    assert end == datetime(2020, 4, 14, 23, 0, 0, tzinfo=timezone.utc)     # ends at the hour boundary


# ── Synthetic fragmented DHFS disk ────────────────────────────────────────────

_SPC = 8                      # sectors per cluster -> 4 KiB clusters (real disks use 4096 sectors)
_CL = _SPC * 512
_DESC_SECTOR, _VIDEO_SECTOR, _N_DESC = 200, 400, 192


def _t(seconds_from_start: int = 0) -> int:
    base = int(datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    return _encode_dhav_date(base + seconds_from_start)


def _desc(dtype, cam_byte, num, begin, end, nxt, last_sectors, prev, vid) -> bytes:
    d = bytearray(DHFS_DESC_SIZE)
    d[0], d[1] = dtype, cam_byte
    struct.pack_into("<H", d, 2, num)
    struct.pack_into("<II", d, 4, begin, end)
    struct.pack_into("<I", d, 12, nxt)
    struct.pack_into("<I", d, 16, last_sectors)
    struct.pack_into("<I", d, 20, prev)
    struct.pack_into("<I", d, 24, vid)
    return bytes(d)


def build_dhfs_disk(recordings, free_clusters=None, cam_base=0x20):
    """
    recordings: list of dict(camera, data, clusters, t0). `data` is split over the listed cluster
    indices (in order). free_clusters: {cluster_index: bytes} of leftover (deleted) footage.
    """
    total = _VIDEO_SECTOR * 512 + _N_DESC * _CL
    disk = bytearray(total)
    disk[: len(DHFS_SIGNATURE)] = DHFS_SIGNATURE
    pos = DHFS_PART_TABLE_OFFSET + DHFS_PART_ENTRIES_START
    struct.pack_into("<I", disk, pos + DHFS_PART_OFF_BOOT, 34)
    struct.pack_into("<Q", disk, pos + DHFS_PART_OFF_START, 0)
    struct.pack_into("<I", disk, pos + DHFS_PART_OFF_LENGTH, total // 512)
    disk[pos + DHFS_PART_ENTRY_SIZE : pos + DHFS_PART_ENTRY_SIZE + 4] = DHFS_PART_END_MAGIC

    bs = 34 * 512
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_BEGIN, _t(0))
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_END, _t(7200))
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_SECTOR_SIZE, 512)
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_SECTORS_PER_CLUSTER, _SPC)
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_DESC_TABLE, _DESC_SECTOR)
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_VIDEO_AREA, _VIDEO_SECTOR)
    struct.pack_into("<I", disk, bs + DHFS_BOOT_OFF_DESC_COUNT, _N_DESC)

    descs = [b"\xfe" + b"\x00" * (DHFS_DESC_SIZE - 1)] * _N_DESC
    va = _VIDEO_SECTOR * 512
    for rec in recordings:
        data, cl = rec["data"], rec["clusters"]
        chunks = [data[i : i + _CL] for i in range(0, len(data), _CL)]
        assert len(chunks) == len(cl), (len(chunks), len(cl))
        cam_byte = cam_base | (rec["camera"] - 1)
        t0 = rec["t0"]
        main = cl[0]
        for n, (idx, chunk) in enumerate(zip(cl, chunks)):
            disk[va + idx * _CL : va + idx * _CL + len(chunk)] = chunk
            nxt = cl[n + 1] if n + 1 < len(cl) else 0
            prev = cl[n - 1] if n else 0
            if n == 0:
                last = -(-len(chunks[-1]) // 512)
                descs[idx] = _desc(1, cam_byte, len(cl), _t(t0), _t(t0 + 3599), nxt, last, 0, main)
            else:
                descs[idx] = _desc(2, cam_byte, n, _t(t0 + n * 5), _t(t0 + n * 5 + 5), nxt, 0, prev, main)
    for idx, data in (free_clusters or {}).items():
        disk[va + idx * _CL : va + idx * _CL + len(data)] = data
    dt = _DESC_SECTOR * 512
    for i, d in enumerate(descs):
        disk[dt + i * DHFS_DESC_SIZE : dt + (i + 1) * DHFS_DESC_SIZE] = d
    return bytes(disk)


def _split_pictures(h264: bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".h264") as tf:
        tf.write(h264)
    with open(tf.name, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        spans, _ = _carve_annexb_run(mm, h264.find(b"\x00\x00\x01\x67"), len(h264))
    os.unlink(tf.name)
    return [(h264[a:b], key) for a, b, _t, key in spans]


_EXT = bytes([0x80, 0x00, 40, 30, 0x81, 0x00, 0x08, 10])     # width/8, height/8; codec 0x8 = H.264, 10 fps


def _dhav_stream(h264: bytes, channel: int, base_ts: int) -> bytes:
    """A DHII-style header sector followed by one DHAV frame per picture (real H.264 payload)."""
    out = bytearray(b"DHII" + b"\x00" * 508)
    for i, (pic, key) in enumerate(_split_pictures(h264)):
        frame = bytearray(make_dhav_frame(channel, i, base_ts + i // 10, ts_ms=(i % 10) * 100,
                                          frame_type=0xFD if key else 0xFC, payload_size=len(pic), ext_data=_EXT))
        # make_dhav_frame filled the payload with filler: splice in the real picture
        hdr = len(frame) - len(pic) - 8
        frame[hdr : hdr + len(pic)] = pic
        out += frame
    return bytes(out)


def _encode(source: str, path: str) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=duration=2:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", path],
        check=True,
    )
    return Path(path).read_bytes()


@pytest.fixture(scope="module")
def two_streams(tmp_path_factory):
    d = tmp_path_factory.mktemp("dhfs")
    base = int(datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    return (_dhav_stream(_encode("testsrc", str(d / "a.h264")), 0, base),
            _dhav_stream(_encode("smptebars", str(d / "b.h264")), 1, base + 3))


def _fragmented(two_streams):
    a, b = two_streams
    na, nb = -(-len(a) // _CL), -(-len(b) // _CL)
    assert 2 * max(na, nb) + 20 < _N_DESC, (na, nb)
    ca = [2 * i + 2 for i in range(na)]                   # A: even clusters (from 2: 0 is the end-of-chain marker)
    cb = [2 * i + 3 for i in range(nb)]                   # B: odd clusters  -> both fully interleaved
    return [dict(camera=1, data=a, clusters=ca, t0=0), dict(camera=4, data=b, clusters=cb, t0=3)], (ca, cb)


@_NEED_FFMPEG
def test_fragmented_recordings_are_reassembled_from_descriptor_chains(temp_dir, two_streams):
    recs, _ = _fragmented(two_streams)
    path = os.path.join(temp_dir, "dhfs.dd")
    Path(path).write_bytes(build_dhfs_disk(recs))
    with EvidenceImage.open(path) as img:
        plugin = DahuaPlugin()
        assert plugin.detect(img) == 1.0
        frames, note = plugin.list_recordings(img)
        assert "2 recording(s)" in note
        segs = sorted(label_all(frames, "ev"), key=lambda s: s.camera)
        assert [s.camera for s in segs] == [1, 4]                  # (0x20|3)&0x0F + 1 == 4
        assert segs[0].start_time == datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
        assert "DHFS 4.1 descriptor chain" in segs[0].notes

        original = {1: two_streams[0], 4: two_streams[1]}
        for s in segs:
            got = b"".join(bytes(img.mm[o.start:o.end]) for o in s.disk_offsets)
            assert got[: len(original[s.camera])] == original[s.camera]   # byte-exact; only sector padding may follow
            assert set(got[len(original[s.camera]):]) <= {0}

        seg, detail = export_segment(img.mm, segs[0], Path(temp_dir) / "out_dhfs")
        assert "error" not in detail, detail
        assert detail["ffprobe_valid"] is True and seg.status == SegmentStatus.PARTIAL


@_NEED_FFMPEG
def test_carve_reports_only_footage_outside_indexed_recordings(temp_dir, two_streams):
    recs, (ca, cb) = _fragmented(two_streams)
    # A deleted recording: DHAV frames sitting in clusters no descriptor points at.
    old = _dhav_stream(_encode("testsrc2", os.path.join(temp_dir, "old.h264")), 2, int(datetime(2025, 4, 1, tzinfo=timezone.utc).timestamp()))
    free_at = max(ca + cb) + 3
    assert free_at + -(-len(old) // _CL) < _N_DESC
    free = {free_at + i: old[i * _CL : (i + 1) * _CL] for i in range(-(-len(old) // _CL))}
    path = os.path.join(temp_dir, "dhfs_deleted.dd")
    Path(path).write_bytes(build_dhfs_disk(recs, free_clusters=free))
    with EvidenceImage.open(path) as img:
        plugin = DahuaPlugin()
        indexed, _ = plugin.list_recordings(img)
        carved, note = plugin.carve(img)
        assert carved, note
        assert "OUTSIDE indexed recordings" in note
        lo = _VIDEO_SECTOR * 512 + free_at * _CL
        hi = lo + len(free) * _CL
        assert all(lo <= f.disk_offset < hi for f in carved)       # only the deleted footage, nothing from indexed clusters
        assert {f.camera for f in carved} == {2}
        assert len(label_all(indexed + carved, "ev")) == 3           # two indexed recordings + one recovered deleted one


def test_chain_never_follows_a_fragment_that_names_another_video(temp_dir):
    """A stale next-pointer into a reused cluster must not splice another recording into this one."""
    a = b"DHII" + b"\x00" * 508 + b"A" * (_CL * 3)
    disk = bytearray(build_dhfs_disk([dict(camera=1, data=a, clusters=[0, 1, 2, 3], t0=0)]))
    dt = _DESC_SECTOR * 512
    # cluster 2's descriptor now belongs to a different recording (video id 50)
    struct.pack_into("<I", disk, dt + 2 * DHFS_DESC_SIZE + 24, 50)
    mm = _Mem(bytes(disk))
    part = read_partitions(mm, len(disk))[0]
    rec = iter_recordings(mm, len(disk), part)[0]
    assert [f.desc_index for f in rec.fragments] == [0, 1]           # stops before the foreign fragment


def test_chain_loop_is_broken(temp_dir):
    a = b"DHII" + b"\x00" * 508 + b"A" * (_CL * 2)
    disk = bytearray(build_dhfs_disk([dict(camera=1, data=a, clusters=[0, 1, 2], t0=0)]))
    dt = _DESC_SECTOR * 512
    struct.pack_into("<I", disk, dt + 2 * DHFS_DESC_SIZE + 12, 1)     # cluster 2 points back to cluster 1
    mm = _Mem(bytes(disk))
    part = read_partitions(mm, len(disk))[0]
    rec = iter_recordings(mm, len(disk), part)[0]
    assert [f.desc_index for f in rec.fragments] == [0, 1, 2]
