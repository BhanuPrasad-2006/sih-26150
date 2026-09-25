# Hikvision DVR/NVR — Format Sheet

**Primary source (read in full, figures inspected, 2026-09-24):**
J. Han, D. Jeong, S. Lee, "Analysis of the HIKVISION DVR File System", ICDF2C 2015, LNICST 157, pp. 189-199,
DOI 10.1007/978-3-319-25512-5_13 ("Han 2015"). Tested on one Hikvision DS-7204HVI-SV DVR with a 160 GB disk.

**Other sources:** FFmpeg `libavformat/mpeg.c` (Hikvision "IMKH" export files are MPEG program streams);
Dragonas et al. 2023 (log records, not used here). MDPI Information 16(11):983 (2025) was read too; its Hikvision
frame format is **rejected** (see §6).

**Status key:** ✅ stated by Han 2015 (and read from its text/figure) · 🔵 inferred or our own choice ·
❓ not published / unverified · ⚠ conflict or ambiguity in the source.
Trust level and cross-checks: `docs/format_verification.md`. **Our code has not been run on a real disk**, but its index layout has been cross-checked against a third party's published parse of a real 1 TB disk (see §7a), which changed the code.

An earlier version of this sheet marked the `0xBA`/`0xBC` prefix, the 1 GB block size and the `OFNI` table as
"from an unverified AI report". They are in Han 2015 itself. That error came from not having read the paper.

---

## 1. Layout (Han §2, Fig. 1)

Master Sector → System Logs → Video Data Area (numerous data blocks) → HIKBTREE (metadata). A backup Master
Sector follows the system logs; a backup HIKBTREE follows the primary one. ✅

## 2. Master sector (§2.1, Fig. 2)

Starts at disk offset **0x200** in Han's disk, but **0x210** on a real disk (the whole file system was shifted by 16 bytes, §7a); the plugin searches a 4 KiB window and adds the shift to every pointer. 256 bytes, little-endian. ✅ Signature `HIKVISION@HANGZHOU` at offset 0.
Field offsets below are relative to the master sector and were **read from the hex-dump figure**; the paper prints
the sample values, which are arithmetically consistent (and the implementation rejects a sector that isn't).

| Offset | Size | Field | Sample value (Han Fig. 2) |
|---|---|---|---|
| 0x38 | u64 | capacity of the hard disk | 0x25433D6000 (~160 GB) |
| 0x50 | u64 | offset to system logs | 0x3D13200 |
| 0x58 | u64 | size of system logs | 0xF42C00 |
| 0x68 | u64 | offset to video data area | 0x4C5E000 |
| 0x78 | u64 | size of a data block | bytes `00 00 00 40` = 0x40000000 (1 GB) ⚠ |
| 0x80 | u32 | total number of data blocks | 0x94 (148) |
| 0x88 | u64 | offset to HIKBTREE1 | 0x25433BDC00 |
| 0x90 | u32 | size of HIKBTREE1 | 0x6000 |
| 0x98 | u64 | offset to HIKBTREE2 (backup) | 0x25433C3C00 |
| 0xA0 | u32 | size of HIKBTREE2 | 0x6000 |
| 0xE0 | u32 | time of last system initialisation (UNIX, UTC) | bytes `37 22 77 54` ⚠ |

⚠ The paper's text gives the block size as `0x400000`, but the figure bytes and the block count agree on 1 GB
(0x25433D6000 ÷ 1 GB = 148 = 0x94, and §2.3 says "generally 1 GB"). ⚠ The text prints the init time as
`0x37227754` (bytes left to right); read little-endian it is 0x54772237 = 2014-11-30 UTC, which fits a 2015 paper.

Self-consistency checks implemented (`master_sector_problems`): block size in range; block count > 0; video area
fits inside the stated capacity; logs end before the video area; backup HIKBTREE follows the primary.

## 3. HIKBTREE (§2.4, Figs. 5-6)

Signature `HIKBTREE` (no hyphen). ✅ Header, page list, 4 KB pages, footer. The header holds created time,
offset to footer, offset to page list, offset to page 1 (Fig. 5a). ✅ The page list starts with the total number
of pages and page offsets (Fig. 5b). 🔵 Only the parts below are used.

**Data block entry — 48 bytes (Fig. 6B):**

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 8 | (FF…) | unknown |
| 0x08 | 8 | existence of video data | `00…` block holds video; `FF…` no video / none recorded ✅ |
| 0x10 | 1 | 0 (or FF when no video) | |
| 0x11 | 1 | channel (1-based camera number) ✅ | |
| 0x18 | 4 | start time (UNIX UTC) ✅ | |
| 0x1C | 4 | end time (UNIX UTC) ✅ | `FF FF FF 7F 00 00 00 00` when not available ✅ |
| 0x20 | 8 | offset of the data block ✅ | in every sample = video area offset + n × 1 GB (checked) |
| 0x28 | 8 | unknown | |

⚠ The paper's text says times are valid "only when the block is full", but its "Recording" sample shows real times
and its "Recorded" sample shows the sentinel; treated as: sentinel ⇒ no time, otherwise use the time.
Entries are located by this fixed structure and validated against the master sector; how the page list and
"next page" pointers tie pages together is only partly shown, so they are not followed. ❓

## 4. Data blocks (§2.3, Fig. 4)

- Block size generally **1 GB**. ✅ A block holds video data followed, at the back, by an **IDR table**. ✅
- Video is **H.264**; each frame is a NAL unit with the 4-byte start code `00 00 00 01`; types `06 09 61 65 67 68`. ✅
- **Before each picture** the block stores a one-byte-id header `0xBA` or `0xBC` after a 3-byte `00 00 01`
  (`BA` before every picture; `BC` also before keyframes in Fig. 4), then the NAL units. ✅ These are the standard
  MPEG-PS pack-header / program-stream-map ids (FFmpeg `mpeg.c` confirms Hikvision files are MPEG-PS), which is why
  other players show noise on raw blocks. 🔵 The bytes that follow `BA`/`BC` are not published; the carver skips them
  with the MPEG-PS length rules and keeps them in the recovered bytes.
- **IDR table:** records start with `OFNI` (`4F 46 4E 49`), fixed **56 bytes** each, written backwards from the end of
  the block; hold index, channel and timestamp of each IDR picture. ✅ **The record layout is not published** ❓, so
  per-frame timestamps are not available.

## 5. What the plugin does

1. `detect()`: master sector signature at 0x200 → confidence 1.0. 🔵
2. `carve()`: if the master sector parses and passes the arithmetic checks, scan **every** data block in
   the video area. Blocks with exactly one live HIKBTREE entry get that entry's channel as the camera and its
   start/end as a **block-level** time window. Blocks with no usable entry (overwritten, wiped by initialisation,
   or missing) are still carved as unindexed footage (camera 0, no window). Blocks with several live entries are
   not assigned. If the master sector is missing or inconsistent, the whole image is carved. 🔵
3. Inside blocks: standards-based carving (MPEG-PS / H.264 Annex B, `stream_carver.py`) including the `BA`/`BC`
   headers above.
4. Segments start UNCERTAIN; PARTIAL only if FFmpeg decodes the export; never COMPLETE.

Why carve blocks whose entry says "no video": Han §3.2 — initialisation resets the HIKBTREE and logs but "all video
data in data blocks will remain".

## 6. Rejected claim: MDPI 2025 "HKVI" frame format

MDPI Information 16(11):983 states a Hikvision frame format with magic `0x484B5649` ("HKVI") at offset 0, type at 4,
size at 8, timestamp at 12, channel at 16, payload at 20 "minus 24 bytes of header overhead". Not implemented:
uncorroborated (Han and FFmpeg describe NAL/PS data, not this), internally inconsistent (payload at 20 but 24-byte
overhead), and the paper's Dahua detection offsets contradict the Dahua spec.

## 7a. Real-disk evidence (added 2026-09-26)

A third party published the parse of a **real 1 TB Hikvision disk** (E01 image `dvr_test_img.E01`, 1,000,204,886,016 bytes;
`github.com/vishwajitsarnobat/HIKVISION-DVR-Tool`, files `analysis/master_sector_analysis.json` and
`analysis/hikbtree_analysis.json`). The repository has **no licence**, so no code or data file was copied: only the numeric
facts below are used, and `backend/tests/test_hikvision_real_disk.py` encodes a small subset. We have **not** seen the disk
image or run our code on it; this is agreement between our parser and an independent parser's readings, plus what it taught us.

| Fact | Result on the real disk | Effect on our code |
|---|---|---|
| Master sector field offsets relative to the signature (0x38 capacity ... 0xE0 init time) | Identical to Han 2015 | Confirmed (was L1) |
| Master sector position | **Signature at 0x210, not 0x200**: the whole file system is shifted by 16 bytes in the image ("extra offset"); every pointer on the disk needs +16 | **Fixed:** the signature is searched for in a 4 KiB window after 0x200 and its distance from 0x200 is added to every pointer. Before, this disk would have been reported as "unknown" |
| Arithmetic (capacity, 931 blocks of 1 GiB, HIKBTREE1 end = HIKBTREE2 start, logs before video area) | All consistent | Our self-consistency check accepts these values |
| HIKBTREE | Header (signature, footer, page-list and page-1 pointers) → page list (page count, one record per page) → 4 KiB pages; entries start at page +80 and each begins with `FF*8`; 17 pages held 855 entries (41-81 per page) | **Added:** structured read via header, page list and pages, with the old blind scan as fallback |
| Entry layout (48 bytes: existence at 8, channel at 17, start at 24, end at 28, block offset at 32) | Identical to Han 2015 | Confirmed |
| No-video entries | Channel **255**, times `0x7FFFFFFF`/`0` (or equal start and end) | Already handled (channel None, no window) |
| Video entries with the "not set" time sentinel | Present (first entry of channels 2-4) | Already handled (camera kept, no window) |
| Video entries whose **end is earlier than the start** | 7 of 852 | **Fixed:** the entry is kept (block and camera) but gets no window; previously it was rejected |
| Block offsets | All 855 = video area + whole 1 GiB blocks, distinct, indexes 0-930 | Confirmed; 76 of 931 blocks had no entry (unindexed footage) |
| Time span of one block | Median 22.6 h, maximum 45.9 h (low-bitrate recording) | Block-level windows are wide; do not read them as per-frame times |
| IDR table (`OFNI`) | 56-byte records in the last ~1 % of each block, size field 56 at +4, **UNIX time of the key frame at +24** | **Added (informational only):** the scan note reports key-frame counts and the time span; not used to cut or assign segments until validated |
| Time labels in that tool's output | Marked "UTC" but are the author's local time (IST): `1646919412` is 13:36:52 UTC, printed as 19:06:52 | We use only the raw epoch values |

Limits of this evidence: one recorder, one disk, one firmware, output of a tool that may itself have errors, no raw bytes
seen (the bytes at entry offsets 0x10 and 0x12-0x17 are unknown, so the structured read does not require them to be zero).

## 7. Facts still to confirm on a real disk

| Fact | Expected | Confirmed? |
|---|---|---|
| Master sector field offsets (Fig. 2 read from image) | as §2 | ✅ real disk (third-party parse), relative to the signature |
| Data block entry offsets (Fig. 6B) | as §3 | ✅ real disk (third-party parse) |
| Block size 1 GB on current firmware / NVRs | 0x40000000 | ✅ on one real disk (0x40000000); NVRs unknown |
| Bytes following `00 00 01 BA` / `BC` | unknown | — |
| `OFNI` record layout | 56 bytes, unknown fields | partly: size at +4 and key-frame time at +24 (one source); other fields unknown |
| Behaviour on H.265 and newer firmware/filesystems | unknown | — |

## 8. Known limitations

- One 2015 DVR (Han) and one real 1 TB disk of unknown model (third-party output). Newer recorders and NVRs are unverified.
- Our code has not read a real disk image; the real-disk facts come from another tool's published output.
- Per-frame timestamps unavailable; time windows are per 1 GB block and may cover several recordings.
- Ambiguity where one block has several entries; those blocks are carved without camera or window.
- Log parsing not implemented.
- No accuracy figures can be reported until known-answer tests pass on a real disk.

*Last updated: 2026-09-26 (real-disk cross-check added; see §7a).*
