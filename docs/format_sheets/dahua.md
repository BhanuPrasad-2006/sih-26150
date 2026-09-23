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
| DHFS superblock location | Partition offset — exact offset not confirmed | ❓ TO VERIFY on real disk |
| DHFS superblock magic | Not yet identified from a verified source | ❓ TO VERIFY |
| Partition table | Standard MBR or no partition table | 🔵 Proposed (MDPI 2025 mentions both) |

**Implementation note (v1):** `list_recordings()` is NOT implemented. The DHFS index layout is not yet verified.
The plugin returns `[]` with the message `"DHFS index parsing not implemented — use carving"`.
Do not add index parsing until the layout is confirmed on a real disk.

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

- DHFS index parsing is not implemented in v1. Recovery relies entirely on carving.
- The timestamp epoch and timezone are assumed but not verified with a known recording.
- Exact meaning of bytes at offsets 0x05, 0x16–0x27 is unknown.
- Frame length plausibility bounds (100 bytes – 10 MB) are proposed, not derived from data.
- All numbers above come from synthetic test images until a real disk is tested (KAT-01 – KAT-08).

---

*Last updated: 2026-09-20. Update this sheet whenever a real disk test confirms or disproves an item.*
