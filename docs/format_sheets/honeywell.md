# Honeywell NVR — Format Sheet

**Source (only one):** J. Yoon and S. Hwang, "Forensic analysis of video data deletion and recovery in
Honeywell surveillance file system", arXiv:2605.07430 (submitted 8 May 2026). Reverse-engineered by binary
diffing on a **single** Honeywell **HN35080200** NVR (H.264, 160 GB and 250 GB disks). Fetched and read in
full 2026-09-23. The paper states its own limit: one device; other models are "expected" to be similar.

**Status key:** ✅ stated in the paper · 🔵 inferred / our own choice · ❓ not in the paper / unverified

## 1. Disk layout (paper §5.1)

| Item | Detail | Status |
|---|---|---|
| Partition scheme | GPT; protective MBR + primary GPT header (LBA 1) + entry array (LBA 2) | ✅ |
| Start sectors | first 40 sectors (~20 KB); "Machine Data" at sector 34 holds device ID and model | ✅ (not parsed) |
| Partition 1 | proprietary video store (the region we carve) | ✅ |
| Partition 2 | fixed 10 GB ext4 (system files) | ✅ (ignored) |
| Trailing 2 GB | unpartitioned, secondary GPT | ✅ (ignored) |
| Partition 1 internals | header (0x0), Video Block List (0x40000), Video Channel List (0x400000), Record State (0x40000000), video data (0x80000000). Little-endian. | ✅ (offsets for this model; index areas not parsed) |

## 2. Video record (paper §5.4.6, Fig. 8) — what the carver uses

Each NAL record is a **20-byte "Custom Header"** followed by Annex B data:

| Offset | Size | Field | Status |
|---|---|---|---|
| 0 | 1 | type: `0x82` = IDR record, `0x02` = non-IDR record | ✅ |
| 1 | 3 | fixed `80 01 00` | ✅ |
| 4 | 2 | width (u16 LE) — `80 07` = 1920 | ✅ |
| 6 | 2 | height (u16 LE) — `38 04` = 1080 | ✅ |
| 8 | 4 | payload length (u32 LE) — IDR example `0x016560` | ✅ (the paper does not say whether it lands exactly on the next header, so the carver resynchronises if it doesn't) |
| 12 | 8 | Unix time in **microseconds** (u64 LE) — `0x000644865C1BCEE6` = 2025-11-26 21:48:41.896 | ✅ |
| 20 | … | `00 00 00 01` + NAL (SPS `27`, PPS `28`, IDR `25`; non-IDR `21`) | ✅ |

- Records for a channel are back-to-back; a channel's data ends with **20 zero bytes** ("End of Channel Data"). ✅
- Formatting, expiration and overwrite **do not erase** the video region. The paper recovers video by extracting from a
  record header to the next delimiter and playing it in ffplay (with or without the custom header). ✅ (§6, §7)
- Timestamp timezone: the example decodes consistently as UTC next to the Unix-seconds block-group time
  (`0x692775A3` = 2025-11-26 21:48:19 UTC). Treated as UTC; the examiner's device clock offset still applies. 🔵

**Known-answer checks** (`backend/tests/test_honeywell.py`): the paper's printed header bytes decode to 1920×1080,
length `0x016560`, and 2025-11-26 21:48:41.896 UTC, matching the paper's text.

## 3. What the plugin does

- `detect()`: 0.9 if a chain of ≥3 valid records is found at partition 1 + `0x80000000` (located via the GPT) or,
  for images ≤256 MiB, anywhere; 0.15 for a bare "Honeywell" string; otherwise 0.0. 🔵
- `carve()`: finds records by structure (header pattern, dimension/length/timestamp sanity, Annex B start code,
  NAL-type/record-type consistency), walks each stream, strips the 20-byte headers (payloads are exported as Annex B),
  starts each stream at its first IDR, keeps distinct on-disk streams as distinct segments, and uses real per-frame
  timestamps. 🔵
- Segments start UNCERTAIN and become PARTIAL only if ffprobe decodes the export. Never COMPLETE.

## 4. Not implemented / limits

- **Camera channel** lives in the Video Channel List (`0x400000`, 16-byte entries: channel, stream type, length, start
  time, start offset), which formatting erases. It is not parsed, so each stream is reported as camera 0. ❓
- Video Block List, Record State and header fields (available memory, next-write offset) are not parsed.
- Only H.264 (the paper's setting); the H.265 layout is unknown. ❓
- Other Honeywell models, firmware versions and real casework are **not validated**. This project has no Honeywell disk.

## 5. Verification performed (2026-09-23)

`backend/tests/manual/e2e_honeywell_real_video_verification.py`: a real libx264 video of an AI-generated face, split into
40 pictures and wrapped in records, as two time-overlapping channel streams plus decoys in a GPT-style image. Both streams
were recovered byte-exact as two separate segments with header timestamps, exported, 40/40 frames decoded with the face
detected, and face search scored 0.80 same-person vs 0.21 different-person. The test data follows the paper's layout, so
this shows the parser matches the paper, not that every real Honeywell disk matches the paper.
