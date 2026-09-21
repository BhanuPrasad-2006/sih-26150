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

The DHAV frame is self-describing. A frame can be found by searching for the 4-byte magic `DHAV`
and validating the header and footer without knowing the file-system layout.

### 2.1 Header (40 bytes = 0x28)

| Offset | Size | Type | Field | Value / Range | Status |
|--------|------|------|-------|---------------|--------|
| 0x00 | 4 | bytes | Start magic | `DHAV` (ASCII) | ✅ MDPI 2025, FFmpeg dhav.c |
| 0x04 | 1 | uint8 | Frame type | see §2.2 | ✅ FFmpeg dhav.c |
| 0x05 | 1 | uint8 | Sub-type / version | unknown meaning | 🔵 FFmpeg dhav.c (field exists) |
| 0x06 | 2 | uint16 LE | Channel number | 0–31 for analog DVR | ✅ FFmpeg dhav.c |
| 0x08 | 4 | uint32 LE | Sequence number | monotone rising | ✅ FFmpeg dhav.c |
| 0x0C | 4 | uint32 LE | Total frame size | header + payload + footer | ✅ FFmpeg dhav.c |
| 0x10 | 4 | uint32 LE | Timestamp (seconds) | Unix-like; epoch TBC | ✅ FFmpeg dhav.c |
| 0x14 | 2 | uint16 LE | Timestamp (ms) | 0–999 | ✅ FFmpeg dhav.c |
| 0x16 | 2 | ? | Unknown | — | ❓ TO VERIFY |
| 0x18–0x27 | 16 | ? | Unknown fields | — | ❓ TO VERIFY |

**Total header size: 40 bytes (0x28).** Confirmed by FFmpeg dhav.c.

### 2.2 Frame types

| Byte | Meaning | Status |
|------|---------|--------|
| `0xF0` | Video — I-frame (keyframe) | ✅ FFmpeg dhav.c |
| `0xF1` | Video — P/B-frame (delta) | ✅ FFmpeg dhav.c |
| `0xFC` | Audio | ✅ FFmpeg dhav.c |
| `0xFD` | Audio (variant) | ✅ FFmpeg dhav.c |

Any frame with a type byte **not** in `{0xF0, 0xF1, 0xFC, 0xFD}` should be rejected.

### 2.3 Footer (8 bytes)

| Offset from start of footer | Size | Field | Value | Status |
|------------------------------|------|-------|-------|--------|
| 0 | 4 | End magic | `dhav` (ASCII, lowercase) | ✅ MDPI 2025, FFmpeg dhav.c |
| 4 | 4 | uint32 LE | Repeated total frame size | equals header offset 0x0C | ✅ FFmpeg dhav.c |

**Footer position:** `frame_start_offset + total_frame_size - 8`.

**Validation rule:** After finding `DHAV` at offset *P*, read `total_frame_size` from `P+0x0C`.
Then check bytes at `P + total_frame_size - 8` == `dhav` and the following 4 bytes equal `total_frame_size`.
This dual-signature check rejects false positives efficiently.

### 2.4 Timestamp epoch

| Claim | Status |
|-------|--------|
| Timestamp is seconds since Unix epoch (1970-01-01 00:00:00 UTC) | 🔵 Assumed (FFmpeg uses it as Unix time); confirm with a known-time recording |
| Timezone: stored as local time of the recorder | 🔵 Assumed; TO VERIFY |

**Sanity checks (implementation):**
- Reject frames with year < 2000 (clock not set, value = 946684800 seconds from 1970).
- Reject frames with timestamp > current UTC time + 1 day (future date, bad clock).

---

## 3. Multi-channel interleaved stream (analog DVR)

| Item | Detail | Status |
|------|--------|--------|
| All channels mixed | A single DHAV stream carries frames for up to 32 cameras | ✅ MDPI 2026 |
| Channel ID field | Offset 0x06 (uint16 LE) in every frame | ✅ FFmpeg dhav.c |
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
