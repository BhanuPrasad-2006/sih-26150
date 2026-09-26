# Dahua DVR/NVR — Format Sheet

**Status key**
- ✅ Verified — confirmed by two or more independent published sources
- 🔵 Proposed — one source only, or inferred; treat as a starting point
- ❓ TO VERIFY — stated in an unverified or AI-generated report; do NOT code against it until confirmed on a real disk

**Primary sources**
1. MDPI Information 16(11):983, 2025 ("MDPI 2025") — open access
2. Dragonas, Lambrinoudakis, Kotsis, Journal of Forensic Sciences 69, 2024 ("Dragonas 2024")
3. MDPI Information 17(5):493, 2026 ("MDPI 2026") — analog DVR multi-channel
4. FFmpeg libavformat/dhav.c (public source code, tag n7.x) — ("FFmpeg dhav.c")
5. Li and Zuo on DHFS structure (cited in Dragonas 2024)

---

## 1. File-system level (DHFS)

| Item | Detail | Status |
|------|--------|--------|
| File-system name | DHFS (Dahua File System) | ✅ Dragonas 2024 |
| Known version | 4.1 | ✅ Dragonas 2024 |
| Used in | NVR (digital IP cameras) and some DVR (analog) | ✅ Dragonas 2024 |
| Some NVR disks use | Standard file system (XFS mentioned) | ✅ MDPI 2025 |
| Some NVR disks use | Mixed DHFS + XFS | ✅ MDPI 2025 |
| DHFS signature | `DHFS4.1` (7 bytes) at the very start of the disk | ✅ Wullen 2025 + Batista extractor (read `DHFS4.1` at offset 0) |
| Partition table | at sector 30 (`0x3C00`); entries begin `0x34` into the sector, 64 bytes each: boot-sector offset (u32 @ +20, sectors, 34 in the samples), partition start (u64 @ +48, sectors), length (u32 @ +56); ends with `AA 55 AA 55` (`0x3D34` after four partitions) | ✅ both sources; positions confirmed against the spec's Fig. 2 hex dump |
| Boot sector | partition start + boot offset; fields at `0x10` begin time, `0x14` end time, `0x2C` bytes/sector (512), `0x30` sectors/cluster (4096), `0x44` descriptor table (sector), `0x48` video area (sector), `0x4C` descriptor count, `0xF8` log | ✅ both sources; Fig. 3 sample: table at sector 187, video area 6656, 29807 descriptors |
| Descriptor table | 32-byte descriptors, one per cluster: `0x01` main, `0x02` fragment; free is `0xFE` (spec) or `0` (Batista); channel byte, next (@12), last-fragment size in sectors (@16, main), prev (@20), video ID (@24, = the main descriptor's own index in the sample) | ✅ agreed; ⚠ free byte differs (both accepted) |
| Cluster address | partition start + video area + index × cluster size | ✅ both |
| Timestamps | same packed layout as DHAV (yr6/mo4/day5/hr5/min6/sec6, +2000), local clock, no timezone | ✅ FFmpeg + Wullen (worked example reproduced) + Batista |
| Camera number | `(channel byte & 0x0F) + 1` (spec: `0x23` → 4). Batista uses `byte − 48 + 1`, which is only right for `0x3X` bytes and gives negative numbers on the spec's own disk | ✅ spec; ⚠ reference formula conflicts (mask used) |
| Declared fragment count | Batista adds 1 to the main descriptor's count; spec does not | ⚠ conflict — chain length is used instead, count is ignored |
| Some NVR disks use XFS / mixed DHFS+XFS | not handled | 🔵 MDPI 2025 |

**Implementation (2026-09-24):** `list_recordings()` reads this index (`backend/plugins/dahua_dhfs.py`) and
reassembles each recording from its cluster chain, with camera and start times. A chain stops at the end marker
(`0`/`0xFFFFFFFF`), a loop, an out-of-range id, a non-fragment descriptor, or a fragment naming a different video
(so a stale pointer cannot splice another recording in). `carve()` then reports only DHAV frames **outside** indexed
clusters (deleted, free or slack space). Verified by known-answer tests from the spec's printed samples, and by a
differential run of an independent extractor (Batista) on the same synthetic disk: same recordings, chains, start
times and bytes. **Not validated on a real Dahua disk.** Descriptor `0` cannot head a chain (0 is the end marker).

---

## 2. DHAV frame structure

**2026-09 correction:** everything in this section was re-derived by downloading
FFmpeg's actual `libavformat/dhav.c` (tag n7.x) and reading it line-by-line,
after an end-to-end test with a real H.264 recording proved the previous
version of this section wrong (export/remux failed against the real FFmpeg
demuxer). The previous table below carried "✅ FFmpeg dhav.c" tags that had
never actually been checked against the source — several were simply wrong:
the frame-type → stream-type mapping was backwards, the channel field was
the wrong width, and the header was documented as fixed-size when it isn't.
Every "✅ FFmpeg dhav.c" tag below has now been checked against actual source
line numbers (see `_dhav_ffmpeg_source.c` fetched 2026-09-23, functions
`dhav_probe`, `read_chunk`, `parse_ext`, `dhav_read_packet`, `get_timeinfo`).

The DHAV frame is self-describing. A frame can be found by searching for the 4-byte magic `DHAV`
and validating the header without knowing the file-system layout.

### 2.1 Header (variable length: 24 bytes fixed + a variable extension block)

The header is **not** fixed-size. `DHAV_TYPE_PARTIAL` (0xF1) frames stop after
byte 0x14 (no timestamp/ext fields at all); every other type has a further
4-byte block plus a variable-length extension TLV block.

| Offset | Size | Type | Field | Value / Range | Status |
|--------|------|------|-------|---------------|--------|
| 0x00 | 4 | bytes | Start magic | `DHAV` (ASCII) | ✅ MDPI 2025, FFmpeg dhav.c |
| 0x04 | 1 | uint8 | Frame type | see §2.2 | ✅ FFmpeg dhav.c |
| 0x05 | 1 | uint8 | Sub-type / version | unknown meaning | 🔵 FFmpeg dhav.c (field exists) |
| 0x06 | 1 | uint8 | Channel number | 0–31 for analog DVR | ✅ FFmpeg dhav.c (corrected: was wrongly documented as uint16) |
| 0x07 | 1 | uint8 | Frame sub-number | unknown meaning | ✅ FFmpeg dhav.c (field exists; previously undocumented) |
| 0x08 | 4 | uint32 LE | Frame/sequence number | monotone rising | ✅ FFmpeg dhav.c |
| 0x0C | 4 | uint32 LE | Total frame size | header + payload + trailer | ✅ FFmpeg dhav.c |
| 0x10 | 4 | uint32 LE | Packed date/time | see §2.4 — NOT a Unix epoch | ✅ FFmpeg dhav.c (corrected: previously wrongly documented as Unix seconds) |
| — if type == 0xF1 (PARTIAL), header ends here (0x14) — | | | | | |
| 0x14 | 2 | uint16 LE | Sub-second counter | approximate; not confirmed to be strict ms | ✅ field exists [FFmpeg dhav.c]; meaning 🔵 |
| 0x16 | 1 | uint8 | Extension block length | bytes of TLV data following | ✅ FFmpeg dhav.c |
| 0x17 | 1 | uint8 | Checksum | not validated by FFmpeg's own demuxer | ✅ field exists [FFmpeg dhav.c] |
| 0x18 | ext_length | TLV | Extension block (codec, width/height, audio params, …) | see §2.5 | ✅ FFmpeg dhav.c (`parse_ext`) |

### 2.2 Frame types

Corrected 2026-09 — the previous table's byte↔meaning mapping was backwards.

| Byte | Meaning | Status |
|------|---------|--------|
| `0xF0` | **Audio** | ✅ FFmpeg dhav.c (`dhav_read_packet`: `type == 0xf0` → `AVMEDIA_TYPE_AUDIO`) |
| `0xF1` | Partial/continuation marker — no payload, no packet emitted | ✅ FFmpeg dhav.c (`read_chunk`: `type == 0xf1` just skips bytes and returns) |
| `0xFC` | **Video — delta frame** (not flagged as keyframe) | ✅ FFmpeg dhav.c (routed to video stream; `pkt->flags \|= AV_PKT_FLAG_KEY` only when `type != 0xfc`) |
| `0xFD` | **Video — keyframe** | ✅ FFmpeg dhav.c (`type == 0xfd` → `AVMEDIA_TYPE_VIDEO`, sets up the video stream) |

Any frame with a type byte **not** in `{0xF0, 0xF1, 0xFC, 0xFD}` should be rejected (`dhav_probe`).

### 2.3 Trailer (8 bytes)

FFmpeg's real demuxer does **not** require a trailer: `read_chunk()` always
treats the last 8 bytes counted by the total-frame-size field as non-payload
(`frame_length - 8 - header_consumed` is handed to the caller as payload
size), but it never checks what those 8 bytes actually contain in the normal
read path. The lowercase `dhav` + repeated-length pattern is only ever
opportunistically checked in one corner case (skipping to the next frame
when no stream is active yet) — it is optional there too.

| Offset from start of trailer | Size | Field | Value | Status |
|------------------------------|------|-------|-------|--------|
| 0 | 4 | End magic | `dhav` (ASCII, lowercase) | 🔵 Proposed — optional in FFmpeg's own demuxer; MDPI 2025 shows it present |
| 4 | 4 | uint32 LE | Repeated total frame size | equals header offset 0x0C | 🔵 Proposed — our own carving convention, unverified as universal |

**This tool still requires it when carving** (unlike FFmpeg's demuxer): raw,
unindexed byte scanning needs a cheap anti-false-positive check that a real,
already-open, sequentially-read file doesn't. This is a **carving-precision
heuristic**, not a claim that the trailer is mandatory in the true on-disk
format. A real disk whose captures lack it would be under-carved (frames
silently skipped), not mis-carved — revisit if real-disk testing shows this
is too strict. See `DHAV_TRAILER_MAGIC` in `backend/plugins/constants.py`.

### 2.4 Packed date/time field (offset 0x10)

**Corrected 2026-09** — this is not a Unix epoch. It is a bit-packed reading
of the device's own local clock, decoded per FFmpeg's `get_timeinfo()`:

| Bits | Field |
|------|-------|
| 0–5 | Seconds |
| 6–11 | Minutes |
| 12–16 | Hours |
| 17–21 | Day |
| 22–25 | Month |
| 26–31 | Year − 2000 |

Status: ✅ FFmpeg dhav.c (`get_timeinfo`). Representable years: 2000–2063.
Timezone: this is the recorder's own local wall-clock reading, with no
embedded UTC offset — consistent with, and the reason for, this project's
existing examiner-supplied `device_utc_offset_minutes` normalization
(`backend/timeline.py: normalize_to_utc()`); never auto-inferred.

### 2.5 Extension TLV block (offset 0x18, `ext_length` bytes)

Selected entries relevant to identifying the payload codec, from FFmpeg's
`parse_ext()`:

| Type byte | Length (incl. type byte) | Fields | Status |
|-----------|---------------------------|--------|--------|
| 0x80 | 4 | skip(1), width/8 (uint8), height/8 (uint8) | ✅ FFmpeg dhav.c |
| 0x81 | 4 | skip(1), video_codec (uint8), frame_rate (uint8) | ✅ FFmpeg dhav.c |
| 0x83 | 4 | audio_channels, audio_codec, sample_rate index | ✅ FFmpeg dhav.c |

Video codec byte (from type 0x81): `0x1`=MPEG4, `0x3`=MJPEG, `0x2`/`0x4`/`0x8`=H.264, `0xc`=HEVC — ✅ FFmpeg dhav.c.
**A frame with no type-0x81 entry (or an unrecognized codec byte) cannot be
identified as a specific codec by FFmpeg's demuxer** — this is why simply
fixing the frame-type byte was not sufficient to make real H.264 payloads
demux correctly; the extension block must be present too.

**Sanity checks (implementation):**
- Reject frames whose packed date bits don't form a valid calendar date/time (`datetime()` constructor raises — catches both garbage bytes and an all-zero/never-set clock, which decodes to an invalid month=0).
- Reject frames decoding to a year < 2000 (the packed field cannot represent earlier years at all).
- Reject frames with a decoded timestamp > current UTC time + 1 day (future date, bad clock).

---

## 3. Multi-channel interleaved stream (analog DVR)

| Item | Detail | Status |
|------|--------|--------|
| All channels mixed | A single DHAV stream carries frames for up to 32 cameras | ✅ MDPI 2026 |
| Channel ID field | Offset 0x06 (uint8) in every frame | ✅ FFmpeg dhav.c (corrected 2026-09: was wrongly documented as uint16) |
| Max channels | 32 (analog DVR); NVR may differ | 🔵 MDPI 2026 |
| Separation method | Group all frames by channel number, then sort each group by timestamp | ✅ MDPI 2026 |

---

### 3a. Frames that straddle interleaved clusters (added 2026-09)

A frame near the end of a cluster continues in one of the same camera's LATER clusters, with other cameras' clusters in
between, so its trailer is not where its length says. `dahua_stitch.py` puts such a frame back together only when:

1. the cluster size is known from the DHFS boot sector (it survives deletion of the descriptors; without it nothing is stitched);
2. the last cluster holds `b"dhav"` + the frame's length at exactly the position the length implies (an 8-byte exact match);
3. that cluster continues with the SAME camera's next frame (frame number within +3), preferred over a bare trailer match;
4. any clusters in between are unambiguous: exactly as many unclaimed, header-less, non-empty clusters as needed. More candidates
   than needed means the frame stays rejected (never guessed).

Measured on generated disks (`tools/make_test_pack.py`): 4 KiB clusters, index wiped, camera 1 clip: **3.33 % of frames right before, 89.17 % after**;
64 KiB clusters: 96.67 % before, 100 % after. Every stitched frame in the tests is byte-identical to the original. Still lost: a frame whose
24-byte HEADER is split across two clusters, and every frame depending on it until the next keyframe. Not validated on a real disk.
The method (channel + frame-number continuity, ±3) follows MDPI Information 17(5):493; the checks above are ours.

---

## 4. Adaptive time-gap segmentation

When the time difference between two consecutive frames of the same channel exceeds T_gap, a new
recording session starts.

```
T_gap = max(T_min, min(T_max, alpha * mu + k * sigma))

where:
  mu, sigma = mean and standard deviation of inter-frame intervals
              over the last W frames (rolling window)
  alpha     = 1.5  (proposed starting value; tune on real data)
  k         = 3.0  (proposed; covers 99.7% of normal variation)
  T_min     = 1 s  (proposed lower bound)
  T_max     = 10 s (proposed upper bound)
  W         = 100 frames (proposed window size)
```

Source: MDPI 2025 describes adaptive thresholding. The specific formula above is proposed for our
implementation; `alpha`, `k`, `T_min`, `T_max`, `W` must be tuned on real disk data.

---

## 5. CP Plus hypothesis

CP Plus is commonly used in India. Some CP Plus recorders are *reportedly* built on Dahua or Xiongmai
platforms. No verified source was found for this claim.

**Design rule:** Detect from disk content, not brand label.
- If a CP Plus disk contains `DHAV` frames → Dahua plugin handles it.
- If it does not → report as unknown; a separate plugin is needed later.

Status: ❓ TO VERIFY when a CP Plus disk is available (KAT-04 extended).

---

## 6. Known limitations

- The DHFS 4.1 index is read when present (section 1); after deletion, recovery relies on carving plus the stitching in section 3a.
- The timestamp epoch and timezone are assumed but not verified with a known recording.
- Exact meaning of bytes at offsets 0x05, 0x16–0x27 is unknown.
- Frame length plausibility bounds (100 bytes – 10 MB) are proposed, not derived from data.
- All numbers above come from synthetic test images until a real disk is tested (KAT-01 – KAT-08).

---

*Last updated: 2026-09-20. Update this sheet whenever a real disk test confirms or disproves an item.*
