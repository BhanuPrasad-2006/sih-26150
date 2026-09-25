# Format Admission Gate and Source Ledger

Every on-disk format this tool parses must pass this gate **before** code is written, and each brand's
result is recorded in the ledger below. Vendor formats are proprietary, so every claim about them comes
from someone else's reverse engineering; the gate exists to decide how far each claim can be trusted.

## Trust levels

| Level | Meaning | What may be implemented |
|---|---|---|
| **L0** | Rumour: marketing text, AI-generated report, unsourced forum post, or nothing found | Nothing. At most a weak vendor-string hint. |
| **L1** | One published source (paper, spec, source code) read in full, with printed sample bytes | Parsing, with results labelled UNCERTAIN; known-answer tests built from the source's own printed samples |
| **L2** | Two or more *independent* sources agree (different authors/implementations), or one primary source whose sample values pass arithmetic self-consistency checks and which an independent implementation confirms | Full parsing; results may reach PARTIAL only after FFmpeg/ffprobe decodes the export |
| **L3** | Confirmed on a real recorder disk with ground truth | Accuracy figures may be reported; COMPLETE requires a hash match against known ground truth |

**Nothing in this repository is L3.** No real recorder disk has been tested.

## The gate (all steps, in order)

1. **Read the primary source itself** (the paper/spec PDF, not a summary, not a search snippet). Extract the printed
   figures and hex samples. Summaries hallucinate: an unread paper cannot justify "verified" or "unverified".
2. **Cross-check with at least one independent source** (a different author or implementation; an FFmpeg/other
   open-source demuxer counts). Write down every **conflict**, not just the agreements.
3. **Arithmetic self-consistency** of the source's own sample (offsets, sizes, counts must fit together).
4. **Known-answer tests**: parse the source's printed sample bytes and assert the values the source states.
5. **Differential test** where an independent implementation exists: run it (read-only, locally) on our test data
   and require agreement. Never copy its code.
6. **Negative tests**: decoys, random data, truncated and overwritten structures must yield nothing, not garbage.
7. **Decode test**: any recovered video must decode in FFmpeg. Byte-exact recovery is checked against what was embedded.
8. **Licence check**: facts (offsets, layouts) may be used with citation; code may be copied only if the licence allows
   (BSD/MIT with notice). No-licence and GPL code is read-only.
9. **Record the verdict here.** Unresolved conflicts are handled conservatively (e.g. accept both values, or rely on a
   field that does not depend on the disputed one).

## Ledger

### Dahua

| Claim | Sources | Level | Notes |
|---|---|---|---|
| DHAV frame: magic, type byte, 1-byte channel, frame number, length, packed date, ext block, ms | FFmpeg `dhav.c` (read line-by-line); Wullen 2025 spec; MDPI 2025 (fields listed); DVR_Dahua uses `DHAV`+`0xFD` | **L2** | Corrected 2026-09 after a real-video test failed |
| Frame type `0xFD` = video keyframe, `0xFC` = delta, `0xF0` = audio | FFmpeg; DVR_Dahua signature `DHAV\xFD` | **L2** | Earlier code had it backwards |
| Packed date bit layout (yr6/mo4/day5/hr5/min6/sec6, +2000) | FFmpeg `get_timeinfo`; Wullen Table V; Batista `decode_timestamp` | **L2** (3 sources) | Local device time, no timezone |
| Footer `dhav` + repeated size | Wullen (size must match header); MDPI (footer with magic, size); FFmpeg (8-byte trailer accounting, tag optional) | **L2** | MDPI also claims a footer *checksum* (12 bytes); FFmpeg shows 8: **conflict, unresolved** |
| DHFS 4.1 disk index: `DHFS4.1` at sector 0, partition table sector 30, boot sector, 32-byte descriptors, cluster chains | Wullen spec + X-Tension code (BSD-3); Batista `dhfs41.py` (independent Python, no licence) | **L2, implemented 2026-09-24** (`dahua_dhfs.py`) | Agree on: signature, table offset 0x3C00, boot-sector fields (0x10/0x14/0x2C/0x30/0x44/0x48/0x4C/0xF8), descriptor offsets (0/1/2-3/4/8/12/16/20/24), video address formula. **Conflicts:** free descriptor byte (`0xFE` in spec, `0` in Batista: both accepted); fragment count (`+1` in Batista: chain length used); camera decode (`&0x0F +1` vs `-48 +1`: the mask is right on the spec's own disk, where the reference gives negative numbers). Differential test: Batista's extractor run on our synthetic disk agreed on recordings, chains, times and bytes |
| CP Plus disks are Dahua-compatible (DHFS/DHAV) | **Business level, documented:** CP Plus is listed as a Dahua OEM seller (SecurityCamCenter "Dahua OEM list"; IPVM "Dahua OEM Directory"), and OEM articles state OEM units generally share Dahua's hardware and core firmware. **Disk level, nothing found:** the public Dahua tools (`dhfs_extractor`, `DVR_Dahua`) never mention CP Plus, and DVRXaminer's page lists CP Plus among supported brands but names only Hikvision (WFS) and Dahua (DHFS) as file systems and says nothing about CP Plus using DHFS. AI-chat answers claiming a "CP PLUS DDNS" entry in Dahua's HTTP API, a patent on DHAV, or forensic suites grouping CP Plus under DHFS were checked on 2026-09-26 and are **not supported** (the DDNS guides only name CP Plus as an OEM) | **L1 (relationship) / L0 (disk layout)** | Plausible and probably true for many models, unproven for any specific one: OEMs "sometimes modify the firmware", and even DVRXaminer advises reading what its detector reports for each drive. The plugin keeps CP Plus at UNCERTAIN with an unverified note; a validation-kit run on a real CP Plus disk is what would settle it |

**Real-device reports for Dahua (2026-09-26).** `DmytroMoisiuk/DVR_Dahua` (GPL-3.0, so only facts are used) carves `DHAV` + `0xFD` up to the `dhav` trailer, which is exactly our frame marker and trailer, and its author lists recovery on real **Dahua DHI-HCVR4104HS-S2, DHI-HCVR5108C-S3 and EZ-IP NVR1A04-4P** recorders (EZ-IP is a Dahua brand). That is a report by the author, not something we have verified, and it covers Dahua-branded devices only, not CP Plus. `gbatmobile/dhfs_extractor` (MIT per its README) is the independent DHFS 4.1 reader our index parser was cross-checked against. Neither repository publishes disk images.

### Hikvision

| Claim | Sources | Level | Notes |
|---|---|---|---|
| Master sector at disk `0x200`, 256 bytes, signature `HIKVISION@HANGZHOU` | Han 2015 §2.1 + Fig. 2 (read in full); MDPI 2025 (signature check) | **L1+** | MDPI is derivative of Han. Implemented 2026-09-24 (`hikvision_index.py`) |
| Master sector fields at 0x38 capacity, 0x50/0x58 log offset/size, 0x68 video area offset, 0x78 block size, 0x80 block count, 0x88/0x90/0x98/0xA0 HIKBTREE1/2 offset+size, 0xE0 init time | Han Fig. 2 (read from the figure image); sample values are arithmetically consistent (0x25433D6000 ÷ 1 GB = 148 = 0x94 blocks; HIKBTREE1 end = HIKBTREE2 offset) | **L1 + self-consistent** | Text says block size `0x400000`; figure bytes read `0x40000000` (1 GB), which matches the "generally 1 GB" text and the block count. Use the arithmetic check |
| HIKBTREE: signature `HIKBTREE`, header, page list, 4 KB pages, 48-byte data-block entries (existence, channel, start/end u32 UTC, block offset) | Han §2.4, Figs. 5-6 | **L1** | Entry offsets read from Fig. 6B; sentinel times `FFFFFF7F 00000000`. Block offset = video area + n × 1 GB checks out on the samples |
| Video data blocks: H.264 NAL with 4-byte start codes, each picture preceded by `00 00 01 BA` (and `BC` at keyframes) | Han §2.3 + Fig. 4 | **L1** | `BA`/`BC` are the MPEG-PS pack-header / program-stream-map IDs (FFmpeg `mpeg.c` confirms Hikvision files are MPEG-PS). **Earlier sheet wrongly called these "from an AI-generated report".** Exact bytes after `BA`/`BC` are not published |
| IDR table at the end of each block: `OFNI`, 56-byte records, filled backwards | Han §2.3 + Fig. 4 | **L1** | Record layout not published. **Earlier sheet wrongly marked this unverified** |
| Frame magic `0x484B5649` ("HKVI"), type at 4, size at 8, timestamp at 12, channel at 16, payload at 20 "minus 24 bytes overhead" | MDPI 2025 §3.2 only | **REJECTED (L0)** | Uncorroborated; contradicts Han (which describes NAL/PS data, not this header); internally inconsistent (payload at 20 but 24-byte overhead); the same paper's Dahua detection offsets (512/1024/2048) conflict with the Dahua spec (offset 0). Not implemented |

**Real-disk cross-check (2026-09-26).** A third party's published parse of a real 1 TB Hikvision disk (unlicensed; facts only) agrees with
our master-sector field offsets (relative to the signature), the 48-byte entry layout, the sentinel and no-video encodings, and the
block arithmetic, which lifts those rows to **L2 (single real-disk source, our code not run on the image)**. It also contradicted
three assumptions, all fixed: the master sector was at **0x210** (a 16-byte shift of the whole file system), the index is
**page-structured** (header, page list, 4 KiB pages), and **7 of 852 video entries end before they start**. Details:
`docs/format_sheets/hikvision.md` §7a. Nothing is L3 until our code is run on a real image.

### Honeywell
| Claim | Sources | Level | Notes |
|---|---|---|---|
| 20-byte record header (type/`80 01 00`/width/height/length/Unix-µs) + Annex B; 20-zero delimiter; GPT layout | Yoon & Hwang, arXiv:2605.07430 (read in full); companion script `dat_carving.py` (same authors, delimiter only) | **L1** | Printed header bytes decode to the paper's stated values (known-answer test). One device model |

### Others
| Brand | Result | Level |
|---|---|---|
| CP Plus | No source | L0 |
| Uniview | Only marketing (UBS block storage); commercial recovery tools exist but are closed | L0 |
| TP-Link, Godrej, Matrix | Nothing found | L0 |

## Public real-disk test data

None found (searched DFRWS, CFReDS, Digital Corpora, GitHub). L3 requires an examiner-produced disk.

## Related capabilities that are not format claims

- **Drive imaging** (`backend/imaging.py`, evidence dialog "Option 3"): read-only copy of a file or raw device into a hashed `.dd`
  with re-verification. Off unless `FORENSIC_ALLOW_LOCAL_ACQUISITION=1`. Tested on ordinary files (including simulated
  unreadable sectors); **not yet run on a real physical drive**. The write-blocker requirement is an examiner attestation, not
  something software can enforce.
- **Object detection** (`backend/object_detection.py`): YOLOX (COCO) when `cv_models/object_detection_yolox_2022nov.onnx` is
  present, otherwise OpenCV's classical HOG person detector (persons only, false positives expected). Decoding maths is
  unit-tested. With the model installed (OpenCV zoo `object_detection_yolox_2022nov.onnx`, Apache-2.0, sha256
  `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`) it was run on three real photographs: person
  (0.93), cat (0.94), cup/spoon/table (0.90/0.68/0.70) were found in the right places. After squashing to a square and
  mp4v compression the cup fell below the default 0.5 threshold, i.e. it can miss. The HOG fallback, on the same person
  photo, returned one wrong-location box and missed the person. This is three photos, not an accuracy measurement.

## Claims checked and not accepted (2026-09-26)

AI-chat answers about Honeywell, Uniview and Matrix were traced to sources before anything was recorded as a fact.

| Claim | Check | Result |
|---|---|---|
| A DFRWS framework "CARVE" recovers deleted Honeywell video | Real: *CARVE: Recovering and Reconstructing Deleted H.264/H.265 Video from Honeywell Surveillance Systems*, Giri, Yoon, Hwang (SKKU SoftSec Lab), DFRWS APAC 2026. Same lab as the arXiv Honeywell file-system paper we implement. Reported: H.264 **and H.265**, timestamps from OCR of on-screen overlays or PRNU camera fingerprints, 99.89 % average recovery (authors' figure). No public code found | **Accepted as a source, not as validation.** Our Honeywell carver is H.264 only (H.265 is a known gap). The recovery figure is theirs, on their devices |
| `haliner/dvr-recover` extracts Honeywell H.264 | It is a GPL-3.0 tool for Panasonic consumer recorders (MPEG-PS chunks ordered by clock). Honeywell uses 20-byte record headers plus Annex B, per the arXiv paper | **Rejected** |
| `tsvetomir/dvrdecode` shows Uniview's format | The repository is "Decode DAHUA DVR clips from raw disk data" (Ruby, 2015), not Uniview | **Rejected** for Uniview |
| Uniview stores plain elementary streams that Scalpel/foremost can carve | No source found | **Unverified (L0)**; the generic carver may or may not find such streams |
| Matrix SATATYA stores files on ext3/ext4, possibly RAID | Searches of Matrix's manuals and wiki found nothing about the file system | **Unverified (L0)**. If a Matrix disk does turn out to be ext4, the tool's foreign-filesystem detection will report it and standard tools (mmls, mount read-only, Autopsy) apply |
