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
| CP Plus disks are Dahua-compatible | Nothing found | **L0** | Hypothesis only |

### Hikvision

| Claim | Sources | Level | Notes |
|---|---|---|---|
| Master sector at disk `0x200`, 256 bytes, signature `HIKVISION@HANGZHOU` | Han 2015 §2.1 + Fig. 2 (read in full); MDPI 2025 (signature check) | **L1+** | MDPI is derivative of Han. Implemented 2026-09-24 (`hikvision_index.py`) |
| Master sector fields at 0x38 capacity, 0x50/0x58 log offset/size, 0x68 video area offset, 0x78 block size, 0x80 block count, 0x88/0x90/0x98/0xA0 HIKBTREE1/2 offset+size, 0xE0 init time | Han Fig. 2 (read from the figure image); sample values are arithmetically consistent (0x25433D6000 ÷ 1 GB = 148 = 0x94 blocks; HIKBTREE1 end = HIKBTREE2 offset) | **L1 + self-consistent** | Text says block size `0x400000`; figure bytes read `0x40000000` (1 GB), which matches the "generally 1 GB" text and the block count. Use the arithmetic check |
| HIKBTREE: signature `HIKBTREE`, header, page list, 4 KB pages, 48-byte data-block entries (existence, channel, start/end u32 UTC, block offset) | Han §2.4, Figs. 5-6 | **L1** | Entry offsets read from Fig. 6B; sentinel times `FFFFFF7F 00000000`. Block offset = video area + n × 1 GB checks out on the samples |
| Video data blocks: H.264 NAL with 4-byte start codes, each picture preceded by `00 00 01 BA` (and `BC` at keyframes) | Han §2.3 + Fig. 4 | **L1** | `BA`/`BC` are the MPEG-PS pack-header / program-stream-map IDs (FFmpeg `mpeg.c` confirms Hikvision files are MPEG-PS). **Earlier sheet wrongly called these "from an AI-generated report".** Exact bytes after `BA`/`BC` are not published |
| IDR table at the end of each block: `OFNI`, 56-byte records, filled backwards | Han §2.3 + Fig. 4 | **L1** | Record layout not published. **Earlier sheet wrongly marked this unverified** |
| Frame magic `0x484B5649` ("HKVI"), type at 4, size at 8, timestamp at 12, channel at 16, payload at 20 "minus 24 bytes overhead" | MDPI 2025 §3.2 only | **REJECTED (L0)** | Uncorroborated; contradicts Han (which describes NAL/PS data, not this header); internally inconsistent (payload at 20 but 24-byte overhead); the same paper's Dahua detection offsets (512/1024/2048) conflict with the Dahua spec (offset 0). Not implemented |

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
