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

## 4. NAL unit structure

Hikvision stores standard H.264/H.265 video. NAL start codes are standard (`\x00\x00\x00\x01`).

| Item | Detail | Status |
|------|--------|--------|
| NAL start code | `\x00\x00\x00\x01` | ✅ Standard H.264/H.265 specification |
| Firmware prefix `0xBA` before NAL | Some firmware variants prepend this byte | ❓ TO VERIFY — from an AI-generated report |
| Firmware prefix `0xBC` before NAL | Another reported variant | ❓ TO VERIFY — from an AI-generated report |
| OFNI marker | Reportedly marks the keyframe (IDR) table at the end of each block | ❓ TO VERIFY |
| OFNI entry size | 56 bytes (reported) | ❓ TO VERIFY |

**WARNING:** Raw NAL start code carving produces very high false-positive rates because `\x00\x00\x00\x01`
appears throughout normal H.264 streams. Do NOT label carved Hikvision results as COMPLETE unless
`ffprobe` decodes the segment cleanly.

---

## 5. Carving approach (experimental)

Because the HIKB-TREE layout is not yet verified, v1 uses **experimental carving** only for Hikvision.

Proposed algorithm:
1. If firmware-prefix bytes (0xBA / 0xBC) are TO VERIFY, skip searching for them.
2. Scan for standard NAL start codes (`\x00\x00\x00\x01`) using `mmap.find`.
3. Collect candidate offsets.
4. Feed candidate regions to `ffprobe` for validation.
5. Label all carved Hikvision segments **UNCERTAIN** by default.
6. Upgrade to **PARTIAL** only if `ffprobe` reports a valid video stream.
7. COMPLETE is not possible via carving alone without a known-answer hash match.

This approach is marked **experimental**. Results must be verified on a real disk before reporting
any accuracy numbers.

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

- Only detection is fully implemented in v1 (master sector magic check).
- Index reading and carving are experimental / not implemented.
- No accuracy numbers can be reported for Hikvision until KAT-01 and KAT-02 pass on a real disk.
- All items marked ❓ must be verified with Han et al. (2015) full text and a real disk hex dump.

---

*Last updated: 2026-09-20. Update this sheet whenever a real disk test confirms or disproves an item.*
