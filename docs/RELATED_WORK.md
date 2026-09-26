# Related work

Sources checked in September 2026 while reviewing an outside literature summary. "Checked" means the paper's existence, title and
abstract were confirmed from its publisher, arXiv or a repository page; where a page could not be opened (MDPI blocked automated
access) only the abstract-level facts below are used. Figures quoted from papers are the **authors' claims about their own devices**,
never results of this tool.

| Source | What it says | What we took / did not take |
|---|---|---|
| Rzayeva et al., *Automated Forensic Recovery Methodology for Video Evidence from Hikvision and Dahua DVR/NVR Systems*, Information 16(11):983 (2025), [doi:10.3390/info16110983](https://doi.org/10.3390/info16110983) | Automated recovery for Hikvision and Dahua: adaptive temporal sequencing, dual header/footer validation of DHFS frames, automatic manufacturer identification. Reports 27 drives, 91.8 % recovery, 96.7 % temporal accuracy, 2.4 % false positives | Already a source of the Dahua format sheet. Our DHAV header + trailer check and adaptive gap threshold follow the same ideas. We do not reproduce their numbers |
| *Forensic Video Recovery from Multi-Channel Analog DVR Systems: Channel Demultiplexing and Temporal Reconstruction from Interleaved DHAV Streams*, Information 17(5):493 (2026), [doi:10.3390/info17050493](https://doi.org/10.3390/info17050493) | Separates interleaved DHAV frames of up to 32 cameras by channel identifier and temporal coherence; stitches with a frame-number tolerance of ±3 and a time difference of at most 1 s. 14 analog Dahua DVR drives, 92.3 % recovery (97.1 % on undamaged disks) | Cited by the Dahua sheet for the channel range. **New in this version:** stitching of frames that straddle interleaved clusters (`backend/plugins/dahua_stitch.py`), using the same idea (channel + frame-number continuity, ±3 tolerance) plus a trailer match. The method and its checks are ours; we did not have the paper's full text |
| Altinisik & Sencar, *Automatic Generation of H.264 Parameter Sets to Recover Video File Fragments*, IEEE TIFS 2021, [arXiv:2104.14522](https://arxiv.org/abs/2104.14522) | Generates the SPS/PPS a fragment lacks, from a dictionary learned on a very large video corpus plus decoder feedback; valid headers in about 11 decoding trials on average over more than 55,000 videos | **Simplified:** we only *borrow* the SPS/PPS of another piece of the same camera (`backend/parameter_sets.py`). We do not generate headers, and no code from the paper is used (none was found) |
| Yoon & Hwang, arXiv:2605.07430, *Forensic analysis of video data deletion and recovery in Honeywell surveillance file system* | Honeywell NVR file system and deleted-video recovery | Already implemented (Honeywell plugin). One device model |
| Han, Jeong & Lee, *Analysis of the HIKVISION DVR File System*, ICDF2C 2015 | First analysis of the Hikvision DVR file system | Already implemented (HIKBTREE index), cross-checked against a third party's published parse of a real disk |
| [hikextractor](https://github.com/fmpfeifer/hikextractor) (GPL-3.0) | Extracts footage from Hikvision disk images; tested on firmware HIK.2011.03.08 (JFL DHD-2104N, DS-7208HQHI-SH/A). States its implementation differs from the 2015 paper; documents no offsets; has a `--physical-order` option for corrupted timestamps | **Facts only, no code copied** (licence). Consistent with what we found on a real disk (the shifted file system). A cheap independent cross-check when a real Hikvision image is available |
| NIST IR 8172, *Assessment of Closed Circuit Television Digital Video Recording and Export Technologies* (2017) | NIST/FBI research on CCTV export formats; links to sample files | Background for export handling. The samples are exports, not disk images |
| Dragonas et al., *IoT forensics: Exploiting log records from the DAHUA technology CCTV systems*, J. Forensic Sci. (2024) | Recorder log records as a forensic source; a Python tool was developed | Logs are a different data source we do not read. The tool's repository could **not** be found in our search, so "released open-source tools" is unverified |

## Not checked

The Nexus Forensics and Skynet multi-camera papers, the commercial tool descriptions (Magnet DVR Examiner, DiskInternals, SalvationDATA and
others: marketing material) and all videos. Nothing in this project relies on them.

## What the review also claimed

That no open tool covers CP Plus, Godrej, Matrix or TP-Link. That matches what we found (see [oem_comparison.md](oem_comparison.md)),
but a negative cannot be proven from the outside.
