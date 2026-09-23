# Hikvision DVR/NVR — Format Sheet

**Status key**
- ✅ Verified — confirmed by two or more independent published sources
- 🔵 Proposed — one source only, or inferred
- ❓ TO VERIFY — from an unverified or AI-generated report; do NOT code against it until confirmed

**Primary sources**
1. Han, Jeong, Lee (2015). "Analysis of the HIKVISION DVR File System." ICDF2C, Springer. ("Han 2015")
2. MDPI Information 16(11):983, 2025 — cites Han 2015 and adds evaluation data ("MDPI 2025")
3. Dragonas et al. (2023). "IoT forensics: Exploiting unexplored log records from the HIKVISION file system."
   Journal of Forensic Sciences. ("Dragonas 2023")

---

## 1. Master sector

| Item | Detail | Status |
|------|--------|--------|
| Master sector disk offset | 0x200 (512 bytes from start of disk) | ✅ Han 2015 (cited in MDPI 2025) |
| Magic text in master sector | `HIKVISION@HANGZHOU` (ASCII, at the start of the sector) | ✅ Han 2015 (cited in MDPI 2025) |
| Sector size | 512 bytes (standard) | ✅ assumed from disk offset |
| Additional fields in master sector | Not yet documented from a verified source | ❓ TO VERIFY |

**Detection rule (v1):** Read 512 bytes at offset 0x200.
If the bytes contain `HIKVISION@HANGZHOU`, return confidence 1.0.
If not found, return confidence 0.0.
Do not read any other fields from the master sector until verified.

---

## 2. Index structure (HIKB-TREE)

| Item | Detail | Status |
|------|--------|--------|
| Index name | HIKB-TREE | ✅ Han 2015 (name verified; cited in MDPI 2025) |
| Index location on disk | Follows the master sector; exact offset not confirmed | ❓ TO VERIFY with Han 2015 paper |
| Entry layout (fields, sizes) | Not yet extracted from a verified source | ❓ TO VERIFY |
| Effect of "delete from menu" | Resets index entry timestamps; video data remains until overwritten | 🔵 Consistent with Han 2015; exact values TO VERIFY |
| Effect of "quick format" | May re-initialise the index but leave data blocks intact | 🔵 Han 2015 (general description) |
| Effect of "full format" | Overwrites data blocks; recovery unlikely | 🔵 Han 2015 |

**Implementation note (v1):** `list_recordings()` is NOT implemented.
The exact byte layout of HIKB-TREE entries is not yet confirmed.
The method returns `[]` with message `"HIKB-TREE index parsing not implemented — TO VERIFY layout first"`.

---

## 3. Data blocks

| Item | Detail | Status |
|------|--------|--------|
| Data block size | 1 GB | ❓ TO VERIFY (stated in an unverified AI report; not confirmed in Han 2015) |
| Block alignment | Unknown | ❓ TO VERIFY |
| Video stored within blocks | Yes — H.264 or H.265 NAL units | 🔵 Inferred from output format |

---

## 4. Video stream structure

**2026-09 review (same method as the Dahua correction):** the "firmware prefix `0xBA`/`0xBC`" items
below came from an unverified AI-generated report. They are not Hikvision-specific: `0xBA` and `0xBC`
are the standard **MPEG program stream** pack-header and program-stream-map start-code IDs
(ISO/IEC 13818-1). FFmpeg's real `libavformat/mpeg.c` (fetched and read 2026-09-23) confirms
Hikvision "IMKH" video files are MPEG-PS (`imkh_cctv` flag; es_type `0x91` = G.711 µ-law audio).
Secondary web sources also describe raw H.264 in data blocks. **Which container a real Hikvision
data block uses is not verified**, so the carver supports both, using only public standards.

| Item | Detail | Status |
|------|--------|--------|
| H.264 NAL start code | `\x00\x00\x01` / `\x00\x00\x00\x01` | ✅ ITU-T H.264 Annex B |
| NAL header / types / SPS→PPS→slice opening | forbidden bit 0, `nal_unit_type` low 5 bits; SPS=7, PPS=8, IDR=5, slice=1 | ✅ ITU-T H.264 §7.3.1 |
| NAL end rule | Next `00 00 00`/`00 00 01` (emulation prevention forbids them inside payloads) | ✅ ITU-T H.264 Annex B |
| MPEG-PS pack header + PES chain | `00 00 01 BA`, marker bits, PES length-delimited packets | ✅ ISO/IEC 13818-1 §2.5.3 |
| Hikvision export files are MPEG-PS ("IMKH" 4-byte header) | | ✅ FFmpeg mpeg.c |
| Firmware prefix `0xBA` / `0xBC` | = MPEG-PS pack header / program stream map IDs | 🔵 Explained by the standard; not Hikvision-specific |
| OFNI marker (IDR table at end of block) | Reportedly marks the keyframe table | ❓ TO VERIFY (also appears in Han 2015 summaries; not parsed) |
| OFNI entry size | 56 bytes (reported) | ❓ TO VERIFY |
| Whether real HDD data blocks store raw H.264, MPEG-PS, or a private wrapper | | ❓ TO VERIFY on a real disk |

---

## 5. Carving approach (standards-based, decode-validated)

The HIKB-TREE layout is not verified, so the carver does **not** parse any Hikvision-specific structure.
It recovers contiguous standard video streams from raw bytes:

1. Single forward scan (`re` over the mmap) for either an MPEG-PS pack start (`00 00 01 BA`) or an H.264
   SPS start code (`00 00 01` + `27|47|67`).
2. **MPEG-PS run:** validate pack-header marker bits (MPEG-1 and MPEG-2 forms), then walk PES packets by
   their length fields until the chain breaks. Requires a video PES (`E0–EF`) and ≥3 elements. Run extent
   is exact. One unit per pack.
3. **H.264 Annex B run:** must open SPS (known `profile_idc`, ≤1 KiB) → PPS → slice; NAL ends follow the
   Annex B rule, so extents are exact **except the last slice** (see limitations). One unit per slice
   (spans tile the run exactly; also covers preceding SPS/PPS/SEI).
4. Byte-contiguous units form one segment (`reconstructor.split_on_gaps`); a gap starts a new segment.
5. Segments start **UNCERTAIN**. Export remuxes with FFmpeg (`-c copy`; MPEG-PS autodetected, raw H.264 via
   `-f h264`); only if `ffprobe` decodes it does status become **PARTIAL**. **COMPLETE is never assigned.**
6. Not available (unverified): channel/camera number (always 0), timestamps (none), HIKB-TREE index.

**Verification performed 2026-09-23** (`backend/tests/manual/e2e_hikvision_real_video_verification.py`,
`backend/tests/test_hikvision_carving.py`): real ffmpeg/libx264 video of an AI-generated face, embedded in
a Hikvision-style image (valid master sector, noise, random decoys resembling SPS/pack starts) as raw H.264
and as MPEG-PS. Recovered bytes were byte-identical to the embedded stream in both forms; exports decoded
(40/40 frames, face detected); face search scored 0.80 same-person vs 0.21 different-person; decoys and
random data yielded zero units. Bugs found and fixed while doing this: a stray SPS-like code before a real
stream absorbed junk into the run (fixed with the SPS/PPS size guard), and a blanket identical-byte trim
truncated real slices (now applied to the last slice only).

**Not proven:** that any real Hikvision recorder writes video this way on disk. This validates the
carver against the public standards, not against real hardware.

---

## 6. Log records

| Item | Detail | Status |
|------|--------|--------|
| Log records present | Yes — formatting, recording status, login events | ✅ Dragonas 2023 |
| Log location | Inside the Hikvision file system partition | 🔵 Inferred from Dragonas 2023 |
| Log parsing | Not implemented in v1 (requires HIKB-TREE layout verification first) | — |

---

## 7. Facts table (confirm before coding)

For each row, state the result when confirmed on a real disk.

| Fact | Expected value | Confirmed? | Confirmed by | Notes |
|------|----------------|-----------|--------------|-------|
| Master sector magic at 0x200 | `HIKVISION@HANGZHOU` | — | — | First check on every disk |
| HIKB-TREE present | Yes | — | — | Read name from master sector fields |
| Data block size | 1 GB | — | — | Measure from disk hex dump |
| OFNI marker | `b'OFNI'` | — | — | Search near block boundaries |
| OFNI entry size | 56 bytes | — | — | Count bytes between entries |
| Firmware prefix | 0xBA or 0xBC before NAL | — | — | Compare hex dumps, two firmware versions |
| Delete resets timestamp | Yes | — | — | Delete one recording; diff master image |

---

## 8. Known limitations

- Detection (master sector magic) and standards-based stream carving are implemented; index reading is not.
- Camera number, timestamps and recording boundaries from the HIKB-TREE index are unavailable (camera=0,
  no time range). Streams from different cameras/times that happen to be byte-contiguous merge into one segment.
- The **last slice** of an H.264 Annex B run has a heuristic end (first ≥16 identical-byte run); if real
  trailing data differs from filler, junk may be included, and a real slice containing such a run would be
  truncated. ffprobe decode-validation gates the PARTIAL label either way.
- Only standard MPEG-PS/H.264 is handled; H.265, private wrappers, and audio-only content are not carved.
- No accuracy numbers can be reported for Hikvision until KAT-01 and KAT-02 pass on a real disk.
- All items marked ❓ must be verified with Han et al. (2015) full text and a real disk hex dump.

---

*Last updated: 2026-09-20. Update this sheet whenever a real disk test confirms or disproves an item.*
