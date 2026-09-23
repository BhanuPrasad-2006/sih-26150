"""
test_honeywell.py — Honeywell NVR record carving (layout: Yoon & Hwang,
arXiv:2605.07430, one device model). Includes known-answer tests built from
the byte values PUBLISHED IN THE PAPER, plus real ffmpeg-encoded video.
"""

import os
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.acquisition import EvidenceImage
from backend.exporter import export_segment, ffmpeg_available, ffprobe_available
from backend.models import SegmentStatus
from backend.plugins.constants import MIN_PLUGIN_CONFIDENCE
from backend.plugins.honeywell import HoneywellPlugin, _partition1_start, _valid_record_at
from backend.plugins.stream_carver import _carve_annexb_run
from backend.reconstructor import label_all
from backend.test_images.gen_test_image import (
    build_gpt_header_image,
    build_honeywell_stream,
    make_honeywell_record,
)

_NEED_FFMPEG = pytest.mark.skipif(
    not (ffmpeg_available() and ffprobe_available()), reason="ffmpeg/ffprobe not on PATH"
)

_BASE_TS_US = int(datetime(2025, 11, 26, 21, 48, 0, tzinfo=timezone.utc).timestamp()) * 1_000_000


# ── Known-answer tests: bytes and values quoted in the paper (§5.4.6, Fig. 8) ──

# Paper Fig. 8: 20-byte Custom Header of a 1920x1080 IDR record + start of its payload.
_PAPER_IDR_HEADER = bytes.fromhex("82800100800738046065010 0E6CE1B5C86440600".replace(" ", ""))
_PAPER_IDR_PAYLOAD_START = bytes.fromhex("00000001274200 33E7403C0113F2CD".replace(" ", ""))
# Paper Fig. 8: a non-IDR record header (length 205) and the start of its payload.
_PAPER_NONIDR_HEADER = bytes.fromhex("02800100800738 04CD00000038CBFD5B86440600".replace(" ", ""))
_PAPER_NONIDR_PAYLOAD_START = bytes.fromhex("000000012 1E201035B".replace(" ", ""))


def _mm_of(data: bytes):
    class _M:
        def __init__(self, b): self.b = b
        def __getitem__(self, k): return self.b[k]
    return _M(data)


def test_paper_idr_header_decodes_to_values_stated_in_paper():
    data = _PAPER_IDR_HEADER + _PAPER_IDR_PAYLOAD_START + b"\x00" * 64
    rec = _valid_record_at(_mm_of(data), 0, len(data))
    assert rec is not None
    assert (rec.width, rec.height) == (1920, 1080)
    assert rec.length == 0x016560                       # "IDR frame has a length of 0x016560 bytes"
    ts = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp() + rec.ts_us / 1e6
    got = datetime.fromtimestamp(ts, tz=timezone.utc)
    assert got.strftime("%Y-%m-%d %H:%M:%S") == "2025-11-26 21:48:41"   # paper: 21:48:41.896, Nov 26 2025
    assert got.microsecond // 1000 == 896


def test_paper_nonidr_header_is_valid_record():
    data = _PAPER_NONIDR_HEADER + _PAPER_NONIDR_PAYLOAD_START + b"\x00" * 64
    rec = _valid_record_at(_mm_of(data), 0, len(data))
    assert rec is not None and rec.rtype == 0x02 and rec.length == 205


def test_bad_headers_rejected():
    good = _PAPER_IDR_HEADER + _PAPER_IDR_PAYLOAD_START + b"\x00" * 64
    assert _valid_record_at(_mm_of(good), 0, len(good)) is not None
    bad_fixed = bytes([good[0], 0x81]) + good[2:]
    assert _valid_record_at(_mm_of(bad_fixed), 0, len(bad_fixed)) is None
    bad_ts = good[:12] + b"\x00" * 8 + good[20:]                       # timestamp 1970
    assert _valid_record_at(_mm_of(bad_ts), 0, len(bad_ts)) is None
    bad_payload = good[:20] + b"\x11\x22\x33\x44\x55" + good[25:]      # no start code
    assert _valid_record_at(_mm_of(bad_payload), 0, len(bad_payload)) is None


# ── GPT partition-1 location (paper §5.1) ─────────────────────────────────────

def test_partition1_start_from_gpt():
    img = build_gpt_header_image(first_lba=40)
    assert _partition1_start(_mm_of(bytes(img)), len(img)) == 40 * 512


def test_partition1_start_none_without_gpt():
    data = os.urandom(8192)
    assert _partition1_start(_mm_of(data), len(data)) is None


# ── Detection ─────────────────────────────────────────────────────────────────

def test_honeywell_detect_random_data_zero_confidence(temp_dir):
    path = os.path.join(temp_dir, "random_honeywell_probe.dd")
    Path(path).write_bytes(os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        assert HoneywellPlugin().detect(img) == 0.0


def test_honeywell_detect_foreign_image_zero_confidence(foreign_img_path):
    with EvidenceImage.open(foreign_img_path) as img:
        assert HoneywellPlugin().detect(img) == 0.0


def test_honeywell_detect_marker_only_reports_low_confidence(temp_dir):
    path = os.path.join(temp_dir, "honeywell_marker.dd")
    Path(path).write_bytes(b"\x00" * 512 + b"HONEYWELL DVR FIRMWARE v2.1" + os.urandom(64 * 1024))
    with EvidenceImage.open(path) as img:
        assert 0.0 < HoneywellPlugin().detect(img) < MIN_PLUGIN_CONFIDENCE


def _payloads(n=5):
    # Structurally valid Annex B payloads (SPS+PPS+IDR first, then slices) — content is filler.
    idr = b"\x00\x00\x00\x01\x67\x42\x00\x1e" + os.urandom(20) + b"\x00\x00\x00\x01\x68\xce\x3c\x80" \
          + b"\x00\x00\x00\x01\x65" + os.urandom(300)
    idr = idr.replace(b"\x00\x00\x00\x00", b"\x11\x11\x11\x11")
    out = [(idr, True)]
    for _ in range(n - 1):
        p = b"\x00\x00\x00\x01\x41" + os.urandom(200)
        out.append((p.replace(b"\x00\x00\x00\x00", b"\x11\x11\x11\x11"), False))
    return out


def test_honeywell_detect_finds_record_chain(temp_dir):
    path = os.path.join(temp_dir, "hw_chain.dd")
    stream = build_honeywell_stream(_payloads(6), _BASE_TS_US)
    Path(path).write_bytes(b"\xCC" * 8192 + stream + b"\xCC" * 8192)
    with EvidenceImage.open(path) as img:
        assert HoneywellPlugin().detect(img) >= MIN_PLUGIN_CONFIDENCE


# ── Carving ───────────────────────────────────────────────────────────────────

def test_honeywell_carve_recovers_payloads_and_timestamps(temp_dir):
    payloads = _payloads(6)
    path = os.path.join(temp_dir, "hw_carve.dd")
    Path(path).write_bytes(b"\xCC" * 4096 + build_honeywell_stream(payloads, _BASE_TS_US) + b"\xCC" * 4096)
    with EvidenceImage.open(path) as img:
        frames, note = HoneywellPlugin().carve(img)
        assert len(frames) == 6
        assert frames[0].is_keyframe and not frames[1].is_keyframe
        assert frames[0].timestamp == datetime(2025, 11, 26, 21, 48, 0, tzinfo=timezone.utc)
        assert (frames[1].timestamp - frames[0].timestamp).total_seconds() == pytest.approx(0.1)
        recovered = b"".join(bytes(img.mm[f.disk_offset:f.disk_offset_end]) for f in frames)
        assert recovered == b"".join(p for p, _ in payloads)     # headers stripped, payloads exact
        segs = label_all(frames, "ev")
        assert len(segs) == 1 and segs[0].status == SegmentStatus.UNCERTAIN
        assert segs[0].start_time == frames[0].timestamp


def test_honeywell_two_streams_not_interleaved(temp_dir):
    """Two channels' streams overlap in time; they must remain two separate segments."""
    a, b = _payloads(4), _payloads(4)
    path = os.path.join(temp_dir, "hw_two.dd")
    Path(path).write_bytes(
        b"\xCC" * 2048 + build_honeywell_stream(a, _BASE_TS_US)
        + b"\xCC" * 2048 + build_honeywell_stream(b, _BASE_TS_US + 50_000) + b"\xCC" * 2048
    )
    with EvidenceImage.open(path) as img:
        frames, _ = HoneywellPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 2
        assert sorted(s.frame_count for s in segs) == [4, 4]


def test_honeywell_leading_nonidr_records_skipped(temp_dir):
    payloads = _payloads(5)
    partial = [payloads[1], payloads[2]] + payloads       # stream begins mid-GOP (start overwritten)
    path = os.path.join(temp_dir, "hw_partial.dd")
    Path(path).write_bytes(b"\xCC" * 2048 + build_honeywell_stream(partial, _BASE_TS_US) + b"\xCC" * 2048)
    with EvidenceImage.open(path) as img:
        frames, note = HoneywellPlugin().carve(img)
        assert len(frames) == 5 and frames[0].is_keyframe
        assert "2 leading non-IDR" in note


def test_honeywell_wrong_length_field_still_recovered(temp_dir):
    """If the length field doesn't land on the next header, resync to it (length-agnostic)."""
    payloads = _payloads(4)
    recs = bytearray()
    for i, (p, idr) in enumerate(payloads):
        r = bytearray(make_honeywell_record(p, idr, _BASE_TS_US + i * 100_000))
        struct.pack_into("<I", r, 8, len(p) + 7)          # off by 7
        recs += r
    path = os.path.join(temp_dir, "hw_badlen.dd")
    Path(path).write_bytes(b"\xCC" * 2048 + bytes(recs) + b"\x00" * 20 + b"\xCC" * 2048)
    with EvidenceImage.open(path) as img:
        frames, note = HoneywellPlugin().carve(img)
        assert len(frames) == 4


def test_honeywell_random_data_yields_nothing(temp_dir):
    path = os.path.join(temp_dir, "hw_rand.dd")
    Path(path).write_bytes(os.urandom(512 * 1024))
    with EvidenceImage.open(path) as img:
        frames, _ = HoneywellPlugin().carve(img)
        assert frames == []


def test_honeywell_list_recordings_not_implemented():
    frames, note = HoneywellPlugin().list_recordings(None)
    assert frames == [] and "not implemented" in note.lower()


def test_honeywell_display_name_states_validation_status():
    name = HoneywellPlugin().display_name.lower()
    assert "unvalidated" in name


# ── Real video ────────────────────────────────────────────────────────────────

@_NEED_FFMPEG
def test_honeywell_real_h264_video_recovered_and_decodes(temp_dir):
    h264 = os.path.join(temp_dir, "clip.h264")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", h264],
        check=True,
    )
    stream = Path(h264).read_bytes()
    # Split into one payload per picture using the public-standard Annex B splitter.
    import mmap as _mmap
    with open(h264, "rb") as fh, _mmap.mmap(fh.fileno(), 0, access=_mmap.ACCESS_READ) as mm:
        spans, _ = _carve_annexb_run(mm, stream.find(b"\x00\x00\x01\x67"), len(stream))
    payloads = [(stream[a:b], key) for a, b, _t, key in spans]
    assert len(payloads) == 10

    path = os.path.join(temp_dir, "hw_real.dd")
    Path(path).write_bytes(b"\xCC" * 4096 + build_honeywell_stream(payloads, _BASE_TS_US, width=320, height=240) + b"\xCC" * 4096)
    with EvidenceImage.open(path) as img:
        assert HoneywellPlugin().detect(img) >= MIN_PLUGIN_CONFIDENCE
        frames, _ = HoneywellPlugin().carve(img)
        segs = label_all(frames, "ev")
        assert len(segs) == 1
        seg = segs[0]
        recovered = b"".join(bytes(img.mm[o.start:o.end]) for o in seg.disk_offsets)
        assert recovered == stream
        seg, detail = export_segment(img.mm, seg, Path(temp_dir) / "hw_out")
        assert "error" not in detail and detail["ffprobe_valid"] is True
        assert seg.status == SegmentStatus.PARTIAL
