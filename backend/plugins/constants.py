"""
constants.py — All magic bytes, field offsets and tunable parameters.

Status tags (search the codebase for these strings to audit coverage):
  # Verified    — confirmed by two or more independent published sources
  # Proposed    — one source or inferred; treat as starting point
  # TO VERIFY   — from an unconfirmed/AI report; validated only when a real disk confirms it

Sources:
  [Han2015]      Han, Jeong, Lee (2015) ICDF2C, Springer — Hikvision file system
  [Dragonas2023] Dragonas et al. (2023) J. Forensic Sci. — Hikvision log records
  [Dragonas2024] Dragonas et al. (2024) J. Forensic Sci. 69 — Dahua DHFS file system
  [MDPI2025]     MDPI Information 16(11):983, 2025 — Dahua and Hikvision DVR/NVRs
  [MDPI2026]     MDPI Information 17(5):493, 2026 — Dahua multi-channel analog DVR
  [FFmpeg-dhav]  FFmpeg libavformat/dhav.c (public source, tag n7.x) — Dahua DHAV encapsulation


Keep all byte values and offsets here. Import from this module only; never inline magic bytes.
"""

# ── DAHUA / DHAV ──────────────────────────────────────────────────────────────
#
# NOTE ON A PAST DOCUMENTATION ERROR (2026-09):
# The values below were re-derived by downloading and reading FFmpeg's actual
# libavformat/dhav.c (n7.x) byte-for-byte, after an end-to-end test with a real
# H.264 recording proved the previous constants wrong (export/remux failed).
# The prior constants in this file carried "Verified [FFmpeg-dhav]" tags that
# were never actually checked against the FFmpeg source — several were wrong
# (frame-type mapping was backwards, the channel field was the wrong width,
# and the header was assumed fixed-size when it is not). See
# docs/format_sheets/dahua.md §2 for the corrected, source-line-cited layout.

# Frame start marker. DHAV is self-describing: search for this 4-byte magic.
DHAV_HEADER_MAGIC = b"DHAV"          # Verified [MDPI2025, FFmpeg-dhav]

# The DHAV header is NOT fixed-size. Fixed part below; a variable-length
# extension block (parsed by FFmpeg's parse_ext()) follows for every frame
# except DHAV_TYPE_PARTIAL, which has no extension block at all.
DHAV_FIXED_HEADER_SIZE = 0x14        # 20 bytes: magic..frame_length..date — Verified [FFmpeg-dhav]
# Bytes past the fixed part, present for every type EXCEPT DHAV_TYPE_PARTIAL:
DHAV_EXT_HEADER_SIZE = 4             # timestamp_ms(2) + ext_length(1) + checksum(1) — Verified [FFmpeg-dhav]
DHAV_MIN_HEADER_SIZE = DHAV_FIXED_HEADER_SIZE + DHAV_EXT_HEADER_SIZE  # 24 bytes (0x18) before any ext TLV data

# Field offsets (all little-endian)
DHAV_OFF_FRAME_TYPE      = 0x04     # uint8  — Verified [FFmpeg-dhav]
DHAV_OFF_SUBTYPE         = 0x05     # uint8  — meaning unknown — Verified field exists [FFmpeg-dhav]
DHAV_OFF_CHANNEL         = 0x06     # uint8  — Verified [FFmpeg-dhav] (NOT uint16 — corrected 2026-09)
DHAV_OFF_FRAME_SUBNUMBER = 0x07     # uint8  — Verified [FFmpeg-dhav] (was entirely missing before)
DHAV_OFF_SEQUENCE        = 0x08     # uint32 LE (frame_number) — Verified [FFmpeg-dhav]
DHAV_OFF_TOTAL_SIZE      = 0x0C     # uint32 LE (frame_length: header + payload + trailer) — Verified [FFmpeg-dhav]
DHAV_OFF_DATE            = 0x10     # uint32 LE, PACKED bitfield date — NOT a Unix epoch — Verified [FFmpeg-dhav]
# Only present when frame type != DHAV_TYPE_PARTIAL:
DHAV_OFF_TIMESTAMP_MS    = 0x14     # uint16 LE — Verified [FFmpeg-dhav] (meaning: sub-second counter, not strictly ms)
DHAV_OFF_EXT_LENGTH      = 0x16     # uint8  — Verified [FFmpeg-dhav]
DHAV_OFF_CHECKSUM        = 0x17     # uint8  — Verified [FFmpeg-dhav] (not validated; FFmpeg skips it too)
DHAV_OFF_EXT_DATA        = 0x18     # start of the variable-length extension TLV block

# Trailing bytes: FFmpeg's read_chunk() always treats the last 8 bytes counted
# by frame_length as non-payload (`frame_length - 8 - header_consumed` is the
# payload size it hands to the demuxer). FFmpeg does NOT require this trailer
# to contain anything in particular — in dhav_read_packet() it only
# OPTIONALLY skips a further 4 bytes if it happens to see the lowercase
# b"dhav" tag right after the payload. For carving raw, unindexed bytes
# (as opposed to demuxing an already-open, sequentially-read file) we still
# require this tag to match: it is a strong, cheap anti-false-positive check
# and every real capture we've been able to construct/inspect carries it.
# This is a carving-precision heuristic, not a claim that it's mandatory in
# the on-disk format — a real disk lacking it would be under-carved by this
# tool, not mis-carved. Revisit if real-disk testing shows this is too strict.
DHAV_TRAILER_SIZE = 8                # Verified [FFmpeg-dhav] (size only, not content)
DHAV_TRAILER_MAGIC = b"dhav"         # Proposed — optional in FFmpeg's own demuxer; required here for carving precision
DHAV_TRAILER_OFF_MAGIC  = 0          # 4 bytes: b"dhav"
DHAV_TRAILER_OFF_LENGTH = 4          # uint32 LE: same value as DHAV_OFF_TOTAL_SIZE (our own convention, unverified on real disks)

# Valid frame type bytes — Verified [FFmpeg-dhav] dhav_probe() + dhav_read_packet()
DHAV_TYPE_AUDIO         = 0xF0      # AVMEDIA_TYPE_AUDIO
DHAV_TYPE_PARTIAL       = 0xF1      # Continuation/partial marker — no ext block, no packet emitted (skipped)
DHAV_TYPE_VIDEO_DELTA   = 0xFC      # Video, routed to the video stream, NOT flagged as a keyframe
DHAV_TYPE_VIDEO_KEYFRAME = 0xFD     # Video, flagged as a keyframe (AV_PKT_FLAG_KEY)
DHAV_VALID_FRAME_TYPES = frozenset({
    DHAV_TYPE_AUDIO,
    DHAV_TYPE_PARTIAL,
    DHAV_TYPE_VIDEO_DELTA,
    DHAV_TYPE_VIDEO_KEYFRAME,
})

# Video codec byte inside extension TLV type 0x81 — Verified [FFmpeg-dhav]
DHAV_EXT_TYPE_VIDEO_CODEC = 0x81
DHAV_VIDEO_CODEC_H264 = frozenset({0x2, 0x4, 0x8})
DHAV_VIDEO_CODEC_MPEG4 = 0x1
DHAV_VIDEO_CODEC_MJPEG = 0x3
DHAV_VIDEO_CODEC_HEVC = 0xC

# Frame length plausibility bounds (proposed — tune on real data)
DHAV_MIN_FRAME_BYTES = 40           # Proposed. 24-byte header + 8-byte trailer + a few payload bytes. Was 100, which
                                    # silently dropped the tiny P-frames of a static scene (found by the accuracy check:
                                    # 1 of ~20 frames recovered). The trailer 'dhav'+length match and the date check
                                    # already reject false positives, so a large minimum is not needed.
DHAV_MAX_FRAME_BYTES = 10 * 1024 * 1024  # Proposed — 10 MB upper bound

# Channel number plausibility
DHAV_MAX_CHANNEL = 31               # 0-based; analog DVRs carry up to 32 channels — [MDPI2026]

# Packed date bitfield sanity bounds — the decoded year, after adding 2000
DHAV_DATE_YEAR_MIN = 2000           # Proposed — reject clocks that were never set
# DHAV_DATE_YEAR_MAX computed at runtime as current year + 1

# Sequence continuity: gap larger than this → start a new segment
DHAV_SEQ_GAP_THRESHOLD = 3          # Proposed [PRD §5.6.1]

# ── CP PLUS (UNVERIFIED DAHUA-COMPATIBLE) ──────────────────────────────────────
# Identifying markers found in CP Plus firmware, banners, configuration, and logs
CPPLUS_IDENTIFYING_MARKERS = (
    b"CP PLUS",
    b"CPPLUS",
    b"CP-PLUS",
    b"CP_PLUS",
    b"CP-UVR",
    b"CP-NVR",
    b"Aditya Infotech",
    b"ADITYA INFOTECH",
)

# ── HIKVISION ─────────────────────────────────────────────────────────────────

HIKV_MASTER_SECTOR_OFFSET = 0x200   # 512 bytes from disk start — Verified [Han2015, MDPI2025]
HIKV_MASTER_SECTOR_MAGIC  = b"HIKVISION@HANGZHOU"  # Verified [Han2015, MDPI2025]

HIKV_INDEX_NAME = b"HIKBTREE"       # Han 2015 sec. 2.4 (the signature has no hyphen); entries: see HIKV_ENTRY_* below

# Han 2015 (read in full 2026-09-24) states these; only the OFNI record LAYOUT is unpublished.
# An earlier version of this file wrongly called them an unverified AI report.
HIKV_DATA_BLOCK_SIZE = 1 * 1024 * 1024 * 1024   # Han 2015 sec. 2.3 + Fig. 2: generally 1 GB
HIKV_OFNI_MARKER     = b"OFNI"                   # Han 2015 sec. 2.3: IDR-table record signature (layout unpublished)
HIKV_OFNI_ENTRY_SIZE = 56                         # Han 2015 sec. 2.3: fixed 56 bytes per record
# NOTE (2026-09): the "0xBA / 0xBC firmware prefix" claims above/below are almost
# certainly not Hikvision-specific: 0xBA and 0xBC are the standard MPEG program
# stream pack-header and program-stream-map start-code IDs (ISO/IEC 13818-1),
# and FFmpeg's mpeg.c demuxer confirms Hikvision "IMKH" video files are MPEG-PS.
# They are now handled as ordinary MPEG-PS structure by the stream carver.
HIKV_NAL_PREFIX_0xBA = 0xBA                       # = MPEG-PS pack_start_code id
HIKV_NAL_PREFIX_0xBC = 0xBC                       # = MPEG-PS program_stream_map id

# Standard H.264/H.265 NAL start code
HIKV_NAL_START_CODE = b"\x00\x00\x00\x01"        # Verified: H.264/H.265 standard

# ── Standards-based stream carving (Hikvision, and any brand with standard video) ──
# These come from PUBLIC STANDARDS, not from any reverse-engineered Hikvision layout:
#   MPEG-PS:  ISO/IEC 13818-1 §2.5.3 (pack header, PES packet framing)
#   H.264:    ITU-T H.264 Annex B (byte stream format) and §7.3.1 (NAL unit header)
MPEG_PS_PES_STREAM_IDS = frozenset(range(0xBB, 0xC0)) | frozenset(range(0xC0, 0xF0))
MPEG_PS_VIDEO_STREAM_ID_MIN = 0xE0
MPEG_PS_VIDEO_STREAM_ID_MAX = 0xEF
MPEG_PS_MIN_ELEMENTS = 3            # Proposed — pack header + >=2 PES packets before we believe a run
H264_NAL_SPS = 7
H264_NAL_PPS = 8
H264_NAL_IDR = 5
H264_NAL_SLICE = 1
H264_VALID_NAL_TYPES = frozenset(range(1, 14)) | frozenset({19, 20})
# profile_idc values registered in ITU-T H.264 Annex A / §7.4.2.1.1
H264_VALID_PROFILE_IDC = frozenset({44, 66, 77, 83, 86, 88, 100, 110, 118, 122, 128, 134, 135, 138, 139, 244})
H264_MAX_PARAM_SET_BYTES = 1024             # Proposed — SPS/PPS are tiny; larger means swallowed junk
H264_MAX_TAIL_NAL_BYTES = 4 * 1024 * 1024   # Proposed — cap for the final NAL when no next start code follows
H264_TAIL_IDENTICAL_RUN = 16                # Proposed — a >=16-byte identical-byte run ends the final NAL

# Minimum confidence score to proceed with scanning
MIN_PLUGIN_CONFIDENCE = 0.6          # Proposed [PRD §2.4, §5.6 pseudo-code]

# ── FOREIGN DISK DETECTION ────────────────────────────────────────────────────

EXT4_SUPERBLOCK_OFFSET = 0x438      # Magic inside ext4 superblock
EXT4_MAGIC             = b"\x53\xEF"  # 0xEF53 in little-endian — ext4 standard

NTFS_MAGIC_OFFSET = 3
NTFS_MAGIC        = b"NTFS    "     # 8 bytes with trailing spaces

BITLOCKER_MAGIC_OFFSET = 3
BITLOCKER_MAGIC        = b"-FVE-FS-"  # 8 bytes

EXFAT_MAGIC_OFFSET = 3
EXFAT_MAGIC        = b"EXFAT   "    # 8 bytes with trailing spaces

# ── SCANNING PARAMETERS ───────────────────────────────────────────────────────

# Rolling-window size for carving scans (mmap.find handles this automatically;
# window size is kept here for documentation and for manual-chunk fallback if needed)
SCAN_WINDOW_BYTES   = 64 * 1024 * 1024   # 64 MB
SCAN_WINDOW_OVERLAP = 256                # bytes of overlap so no marker is missed at a boundary

# Hashing chunk size (single-pass read; keep a multiple of 4096 for alignment)
HASH_CHUNK_BYTES = 64 * 1024 * 1024     # 64 MB

# ── ADAPTIVE GAP FORMULA DEFAULTS ─────────────────────────────────────────────
# T_gap = max(T_MIN, min(T_MAX, ALPHA * mu + K * sigma))
# Tune these on real disk data before reporting accuracy numbers.
GAP_ALPHA = 1.5     # Proposed
GAP_K     = 3.0     # Proposed (covers ~99.7% of normal variation)
GAP_T_MIN = 1.0     # seconds — Proposed lower bound
GAP_T_MAX = 10.0    # seconds — Proposed upper bound
GAP_WINDOW_W = 100  # frames — rolling window size for mu/sigma — Proposed

# ── HONEYWELL NVR (from a published paper, ONE device model) ──────────────────
# Source: Yoon & Hwang, "Forensic analysis of video data deletion and recovery in
# Honeywell surveillance file system", arXiv:2605.07430 (May 2026) — analysis of a
# single Honeywell HN35080200 NVR via binary diffing. Not validated on other models
# or on real casework by this project.
HW_REC_HEADER_SIZE = 20                  # §5.4.6: 20-byte "Custom Header" before each NAL record
HW_REC_TYPE_IDR = 0x82                   # §5.4.6: 0x82 = IDR frame record
HW_REC_TYPE_NONIDR = 0x02                # §5.4.6: 0x02 = non-IDR frame record
HW_REC_FIXED = b"\x80\x01\x00"           # §5.4.6: fixed 3 bytes after the type byte
# header: [0]=type [1:4]=80 01 00 [4:6]=width u16 [6:8]=height u16 [8:12]=length u32 [12:20]=Unix time µs u64 (LE)
HW_REC_MIN_DIM = 64
HW_REC_MAX_DIM = 16384
HW_REC_MAX_PAYLOAD = 32 * 1024 * 1024    # Proposed sanity cap
HW_END_OF_CHANNEL_DELIMITER = b"\x00" * 20   # §5.4.6: 20 zero bytes end each channel's data
HW_VIDEO_DATA_OFFSET = 0x80000000        # §5.4.1/§5.4.6: video region offset within partition 1 (this model)
HW_GPT_SECTOR = 512
HW_MAX_TS_BACKSTEP_US = 1_000_000        # Proposed: timestamps in a stream may not go back by >1 s
HW_DETECT_REGION_BYTES = 64 * 1024 * 1024
HW_DETECT_WHOLE_IMAGE_MAX = 256 * 1024 * 1024
HW_DETECT_MIN_RECORDS = 3                # Proposed: consecutive valid records to believe a Honeywell stream


# ── HIKVISION INDEX (Han, Jeong, Lee 2015, ICDF2C - read in full, figures 2/5/6) ──
# Field offsets are read from the paper's hex-dump figures; the paper's sample values are
# arithmetically self-consistent (see docs/format_verification.md).
# Offsets below are relative to the master sector start (disk offset 0x200). Little-endian.
HIKV_MS_SIZE = 256                      # section 2.1
HIKV_MS_OFF_CAPACITY      = 0x38        # u64  Fig. 2
HIKV_MS_OFF_LOG_OFFSET    = 0x50        # u64
HIKV_MS_OFF_LOG_SIZE      = 0x58        # u64
HIKV_MS_OFF_VIDEO_AREA    = 0x68        # u64  offset to video data area
HIKV_MS_OFF_BLOCK_SIZE    = 0x78        # u64  size of a data block (1 GB in the sample)
HIKV_MS_OFF_BLOCK_COUNT   = 0x80        # u32  total number of data blocks
HIKV_MS_OFF_BTREE1_OFFSET = 0x88        # u64
HIKV_MS_OFF_BTREE1_SIZE   = 0x90        # u32
HIKV_MS_OFF_BTREE2_OFFSET = 0x98        # u64  backup HIKBTREE
HIKV_MS_OFF_BTREE2_SIZE   = 0xA0        # u32
HIKV_MS_OFF_INIT_TIME     = 0xE0        # u32  UNIX UTC time of the last system initialisation
HIKV_BTREE_SIGNATURE = b"HIKBTREE"      # section 2.4
# Data block entry (Fig. 6B): 48 bytes
HIKV_ENTRY_SIZE = 48
HIKV_ENTRY_OFF_EXISTENCE = 0x08         # 8 bytes: 00.. = block holds video, FF.. = none
HIKV_ENTRY_OFF_CHANNEL   = 0x11         # u8 (1-based camera number)
HIKV_ENTRY_OFF_START     = 0x18         # u32 UNIX UTC
HIKV_ENTRY_OFF_END       = 0x1C         # u32 UNIX UTC
HIKV_ENTRY_OFF_BLOCK     = 0x20         # u64 offset of the data block
HIKV_TIME_SENTINEL_START = 0x7FFFFFFF   # "FF FF FF 7F 00 00 00 00" = no valid time
HIKV_TIME_SENTINEL_END   = 0
HIKV_BLOCK_SIZE_MIN = 1 * 1024 * 1024
HIKV_BLOCK_SIZE_MAX = 16 * 1024 * 1024 * 1024
HIKV_BTREE_MAX_BYTES = 16 * 1024 * 1024


# ── DAHUA DHFS 4.1 DISK INDEX ─────────────────────────────────────────────────
# Sources (see docs/format_verification.md): Wullen 2025, "Forensic analysis of the filesystem
# Dahua DHFS 4.1" (spec + BSD-3 X-Tension, github.com/dw2102/X-Ways-DHFS4_1-X-Tension) and,
# independently, G. Batista's dhfs_extractor (Python, github.com/gbatmobile/dhfs_extractor,
# read only, no code copied). Both agree on everything below except where noted.
# Multi-byte numbers little-endian; sector = 512 bytes unless the boot sector says otherwise.
DHFS_SIGNATURE = b"DHFS4.1"              # first sector of the disk
DHFS_PART_TABLE_OFFSET = 0x3C00          # sector 30
DHFS_PART_ENTRIES_START = 0x34           # entries begin this far into the partition-table sector
DHFS_PART_ENTRY_SIZE = 64
DHFS_PART_OFF_BOOT = 20                  # u32: boot sector offset (sectors, from partition start; 34 in the samples)
DHFS_PART_OFF_START = 48                 # u64: partition start (sectors)
DHFS_PART_OFF_LENGTH = 56                # u32: partition length (sectors)
DHFS_PART_END_MAGIC = b"\xAA\x55\xAA\x55"
DHFS_MAX_PARTITIONS = 16
# Boot sector (Wullen Table II, Fig. 3 sample: descriptor table sector 187, video area sector 6656,
# 29807 descriptors, 512 B/sector, 4096 sectors/cluster, log at sector 43520)
DHFS_BOOT_OFF_BEGIN = 0x10               # u32 packed time: start of recording
DHFS_BOOT_OFF_END = 0x14                 # u32 packed time: end of recording
DHFS_BOOT_OFF_SECTOR_SIZE = 0x2C         # u32
DHFS_BOOT_OFF_SECTORS_PER_CLUSTER = 0x30 # u32
DHFS_BOOT_OFF_DESC_TABLE = 0x44          # u32 sectors from partition start
DHFS_BOOT_OFF_VIDEO_AREA = 0x48          # u32 sectors from partition start
DHFS_BOOT_OFF_DESC_COUNT = 0x4C          # u32 number of 32-byte descriptors (= number of clusters)
DHFS_BOOT_OFF_LOG = 0xF8                 # u32 sectors
DHFS_DESC_SIZE = 32
DHFS_DESC_MAIN = 0x01                    # first cluster of a recording; entry point of the chain
DHFS_DESC_FRAGMENT = 0x02                # later cluster of a recording
DHFS_DESC_FREE_VALUES = frozenset({0xFE, 0x00})   # spec says 0xFE; Batista treats 0 as free (CONFLICT: accept both)
DHFS_DESC_OFF_CHANNEL = 1                # camera = (byte & 0x0F) + 1   (spec; Batista: byte - 48 + 1, same for 0x30-0x3F)
DHFS_DESC_OFF_COUNT = 2                  # u16: fragment count (main; Batista adds 1 — CONFLICT, chain length is used instead) / fragment number
DHFS_DESC_OFF_BEGIN = 4                  # u32 packed time
DHFS_DESC_OFF_END = 8                    # u32 packed time
DHFS_DESC_OFF_NEXT = 12                  # u32 next descriptor id (0 or 0xFFFFFFFF = end of chain)
DHFS_DESC_OFF_LAST_SIZE = 16             # u32 (main only): size of the last fragment in sectors
DHFS_DESC_OFF_PREV = 20                  # u32 (fragments): previous descriptor id
DHFS_DESC_OFF_VIDEO_ID = 24              # u32: main descriptor index of the recording (a main descriptor's own index in the sample)
DHFS_MAX_DESCRIPTORS = 50_000_000
