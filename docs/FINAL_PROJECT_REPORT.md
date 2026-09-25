# Final Project Report

**Multi-Vendor DVR/NVR Forensic Analysis Tool: standardised acquisition, recovery, analysis and reporting of surveillance evidence**

Smart India Hackathon 2026 · Problem Statement SIH26150 · National Technical Research Organisation (NTRO) · Category: Software

Companion documents: [System Architecture](SYSTEM_ARCHITECTURE.md) · [User Manual](USER_MANUAL.md) · [SOP](SOP.md) · [Validation Report](VALIDATION_REPORT.md) · [OEM Comparison](oem_comparison.md) · [Format Admission Gate](format_verification.md) · [Accuracy Measurement](accuracy_measurement.md)

---

## Abstract

Surveillance recordings are frequently the decisive evidence in an investigation, yet DVR/NVR recorders from different vendors store video in proprietary disk layouts, indexes and frame containers that general forensic tools cannot read. We built a vendor-agnostic forensic platform with a single workflow: read-only acquisition with SHA-256 and MD5 hashing, brand identification through a plugin architecture, index parsing and frame carving, timeline reconstruction, lossless export, video analytics (faces, objects, motion), a hash-chained audit log, and court-oriented reporting with a Section 63(4) BSA 2023 certificate template. Vendor parsers were implemented only where a public, checkable source exists: Dahua (DHFS 4.1 index and DHAV frames), Hikvision (HIKBTREE index and MPEG-PS/H.264 blocks) and Honeywell (record stream); a standards-based generic carver covers other recorders that store standard streams. The tool never labels a carved recording COMPLETE and never states a recovery percentage without supplied ground truth; a dedicated module measures frame recall, precision, ordering and byte placement against such ground truth. The system passes 203 automated tests on disk images generated from the published specifications around real encoded video. It has not been validated on a real recorder disk, four of the eight named vendors have no vendor-specific support because no public format documentation exists, and this report states those limits as findings rather than omissions.

## 1. Introduction

### 1.1 Problem

DVR/NVR manufacturers, including Dahua, CP Plus, Honeywell, TP-Link, Godrej, Uniview, Hikvision and Matrix, use proprietary storage formats, file systems, metadata and encodings. The lack of standardisation forces investigators onto multiple vendor tools, with inconsistent results, timestamp synchronisation problems, difficulty recovering deleted footage, and a fragile chain of custody.

### 1.2 Objectives (from the problem statement) and outcome

| Objective | Outcome |
|---|---|
| Identify DVR/NVR models automatically | Signature-based brand identification (not model identification) |
| Parse proprietary file systems | Dahua DHFS 4.1, Hikvision HIKBTREE (from public sources; unvalidated on hardware) |
| Create forensic images | Imaging module built; tested on files, not on a physical drive |
| Extract and decode proprietary video | DHAV, Hikvision PS/H.264, Honeywell records, generic MPEG-PS/H.264 |
| Recover deleted footage | Carving of un-indexed regions; synthetic-disk results only |
| Normalise timestamps | Examiner-supplied UTC offset; no automatic drift correction |
| MD5 and SHA-256 hashing, chain of custody | Implemented, tested |
| Correlate events across cameras | Time-window correlation |
| Reports | PDF with BSA 2023 §63(4) certificate template |
| AI analytics: face, object, motion | YuNet/SFace, YOLOX, frame differencing |
| Support at least five to six OEMs | **Not met**: see §6 |

## 2. Related work and sources

Vendor formats were taken only from material that could be read and cross-checked:

- **Hikvision:** J. Han, D. Jeong, S. Lee, *Analysis of the HIKVISION DVR File System*, ICDF2C 2015 — master sector, HIKBTREE entries, data blocks with MPEG-PS headers, IDR table.
- **Dahua DHFS:** D. Wullen, *Forensic analysis of the filesystem Dahua DHFS 4.1* (2025), with an independent open-source extractor (Batista) and a BSD-licensed X-Tension for cross-checking; conflicts between them were resolved conservatively.
- **Dahua DHAV frames:** FFmpeg `libavformat/dhav.c`. Our first constants were wrong; end-to-end testing exposed it and the layout was re-derived from this source.
- **Honeywell:** J. Yoon and S. Hwang, *Forensic analysis of video data deletion and recovery in Honeywell surveillance file system*, arXiv:2605.07430 (one device model).
- **Standards:** ISO/IEC 13818-1 (MPEG-PS) and ITU-T H.264 Annex B for the generic carver.
- A 2025 MDPI description of a "HKVI" Hikvision frame format was examined and **rejected** as uncorroborated and internally inconsistent.
- Commercial recovery tools (Disk Drill, Hetman, Dolphin, Recoverit, DFL-DVR) were considered; their internals are proprietary and cannot be reused.

No public documentation or peer-reviewed analysis was found for Uniview, TP-Link, Godrej or Matrix (searched September 2026).

## 3. Method

### 3.1 Evidence discipline

The tool treats every format claim as a hypothesis with an evidence tag. A **Format Admission Gate** (`format_verification.md`) defines trust levels: L0 unsourced, L1 one source read, L2 corroborated and tested on synthetic data, L3 validated on a real disk. A vendor is described as "supported" only at the level actually reached; nothing is L3.

### 3.2 Recovery pipeline

Read-only open and hash → plugin detection → index read where one is documented → frame/record carving with per-candidate validation → reconstruction by camera, stream and time gaps → lossless export (`ffmpeg -c copy`) → decode check (`ffprobe`) → labelling → final re-hash. Status is `UNCERTAIN` unless the export decodes (`PARTIAL`); `COMPLETE` is not assigned by carving.

### 3.3 Verification strategy

Because no recorder disk was available, disks were built from the specifications around real ffmpeg-encoded video of a person; parsers were also fed the byte values printed in the papers (known-answer tests). A ground-truth accuracy module measures the result of a recovery against a known-good video, a recording log, or the original pre-deletion image.

## 4. Implementation

A FastAPI backend (≈ 13,400 lines of Python, ≈ 4,300 of them tests), a build-free vanilla-JavaScript single-page front end (≈ 4,600 lines), SQLite or Supabase/Postgres storage, ReportLab reports, OpenCV for analytics and FFmpeg for export. Detail is in the [System Architecture](SYSTEM_ARCHITECTURE.md).

Key features: single-examiner login with bcrypt, lockout and idle timeout; hash-chained audit log `H_n = SHA-256(t_n ∥ action_n ∥ params_n ∥ H_{n-1})`; brand plugins with explicit trust wording; index-first-then-carve recovery; per-format format sheets; drive imaging with bad-sector accounting; YuNet, SFace and YOLOX analytics; cross-camera correlation; accuracy against ground truth; PDF report with certificate template.

## 5. Results

### 5.1 Verification results (synthetic disks around real video)

| Result | Status |
|---|---|
| Dahua: DHAV carve → export → decode → face detected → reference photo matches, a different photo does not | Pass |
| Hikvision and Honeywell: same end-to-end run, including decoy streams and an un-indexed block | Pass |
| Dahua DHFS: fragmented, interleaved recordings reassembled through the index | Pass |
| Known-answer values from Han 2015, Wullen 2025 and the Honeywell paper reproduced | Pass |
| Tampering with one byte of evidence is detected | Pass |
| Accuracy module: identical video 100 %, truncated and different videos give the expected lower values | Pass |
| Object detection (YOLOX) on three real photos: person 0.93, cat 0.94, cup/spoon/table found; a cup missed after compression | Sanity check only |
| Automated suite | 203 passing (195 without a live database) |

### 5.2 A finding produced by the accuracy method

On a fragmented Dahua disk with its index wiped, the carver found only 21 of the 40 frames (byte recall 86.5 %). Ground-truth comparison traced this to a minimum-frame-size filter (100 bytes) that rejected the tiny P-frames of a quiet camera; lowering it to 40 recovered all 40 frames (byte recall 92.1 %, placement precision 100 %). This shows the value of measuring against ground truth and also that carving heuristics tuned without it can silently lose evidence.

### 5.3 Performance

Not measured. No benchmark was run on large images; runtime and memory on multi-terabyte disks are unknown.

## 6. Comparative analysis of the OEMs

Full table: [oem_comparison.md](oem_comparison.md).

| OEM | Public documentation | Support delivered |
|---|---|---|
| Dahua | DHFS 4.1 spec (2025), DHAV (FFmpeg) | Index + frame carving; unvalidated on hardware |
| Hikvision | One 2015 paper (one DVR model) | Index + block carving; per-frame time unavailable |
| Honeywell | One 2026 paper (one NVR model) | Record carving with real timestamps; unvalidated |
| CP Plus | None specific | Routed through Dahua on an unverified assumption |
| TP-Link, Godrej, Uniview, Matrix | None found | Detection hint only; generic carving fallback |

**Conclusion on the "five to six OEMs" requirement.** It was not met in an honest sense: two OEMs are implemented from public sources, one from a single paper, one by assumption, and four not at all beyond a generic fallback. We chose not to invent offsets for undocumented vendors, because a plausible but wrong parser produces confident false evidence. Meeting the requirement needs sample disks or vendor documentation.

## 7. Discussion

**What the work shows.** A single forensic workflow can wrap very different vendor formats behind one plugin contract, with hashing, audit, reporting and analytics shared. Explicit trust wording and refusal to over-claim were built into the data model and UI rather than left to the examiner.

**Threats to validity.** The disk builders and parsers share authors and sources, so a common misreading would go undetected; real deletion and wear patterns are absent from the tests; the formats rest on very few devices and papers; analytics were only spot-checked on a few images.

**Ethics and law.** Face similarity is presented as candidate leads for human review, never identification. The certificate is a template to support an examiner, not legal advice; admissibility must be assessed by counsel and by the laboratory's procedures (BSA 2023 §63(4), ISO/IEC 27037).

## 8. Limitations

1. No real-disk validation; all offsets could be wrong on real devices.
2. Four vendors unsupported beyond a generic fallback; CP Plus and Honeywell weakly supported.
3. Hikvision per-frame timestamps unavailable (record layout unpublished).
4. Carving never yields `COMPLETE`.
5. Drive imaging untested on a physical drive; write-blocking cannot be enforced in software.
6. Analytics: sampled frames; small or dark subjects missed; validated on a handful of images.
7. Timestamps depend on an examiner-supplied clock offset; no drift correction.
8. Single examiner, localhost only; no roles.
9. No performance benchmarks.

## 9. Conclusion and future work

The project delivers a working, tested, honestly labelled platform and the machinery (admission gate, ground-truth measurement, validation protocol) to move each vendor from "specified" to "validated". It does not yet deliver validated recovery from real recorders. Future work, in priority order:

1. Run the validation protocol ([Validation Report §7](VALIDATION_REPORT.md)) on real Dahua/CP Plus and Hikvision recorders; promote or correct formats.
2. Test imaging on a physical disk behind a write blocker.
3. Obtain samples or documentation for Uniview, TP-Link, Godrej and Matrix, and confirm or refute the CP Plus assumption.
4. Evaluate analytics on real surveillance footage; add clock-drift estimation from on-screen time.
5. Benchmark on large images; consider streaming carving instead of memory maps.
6. Multi-examiner roles, if operational use demands it.

## 10. Requirement traceability

| Problem-statement item | Where |
|---|---|
| Device identification | `backend/plugins/`, `registry.py` |
| Acquisition | `acquisition.py`, `imaging.py`, evidence dialog |
| File-system and format parsing | `dahua_dhfs.py`, `hikvision_index.py`, `stream_carver.py`, format sheets |
| Recovery | plugins' `carve()`, `reconstructor.py`, `exporter.py` |
| Hashing MD5/SHA-256 | `acquisition.py`, `imaging.py` |
| Timeline analysis | `timeline.py`, `correlation.py`, Timeline screen |
| Chain of custody | `audit.py`, Audit screen, report |
| Reporting | `reporting.py`, BSA §63(4) certificate |
| Machine learning | `face_detection.py`, `face_search.py`, `object_detection.py`; `motion.py` (non-ML, labelled so) |
| Comparative analysis of OEMs | `oem_comparison.md` |
| SOP | `SOP.md` |
| System architecture documentation | `SYSTEM_ARCHITECTURE.md` |
| User manual | `USER_MANUAL.md` |
| Validation report | `VALIDATION_REPORT.md` (states that real validation is pending) |
| Functional prototype | This repository |
| DVR/NVR forensic image | **Not available** — no real recorder image was obtained |

## References

1. J. Han, D. Jeong, S. Lee, "Analysis of the HIKVISION DVR File System," ICDF2C 2015, LNICST 157, pp. 189–199. DOI 10.1007/978-3-319-25512-5_13.
2. D. Wullen, "Forensic analysis of the filesystem Dahua DHFS 4.1," 2025.
3. J. Yoon, S. Hwang, "Forensic analysis of video data deletion and recovery in Honeywell surveillance file system," arXiv:2605.07430, 2026.
4. FFmpeg, `libavformat/dhav.c`.
5. ISO/IEC 13818-1, *Generic coding of moving pictures and associated audio: Systems*.
6. ITU-T Rec. H.264, Annex B (byte stream format).
7. OpenCV model zoo: YuNet (face detection), SFace (face recognition), YOLOX (object detection), Apache-2.0.
8. Bharatiya Sakshya Adhiniyam, 2023, Section 63(4); ISO/IEC 27037:2012.
