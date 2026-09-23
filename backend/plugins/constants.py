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
DHAV_MIN_FRAME_BYTES = 100          # Proposed — smaller is almost certainly a false positive
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

HIKV_INDEX_NAME = b"HIKB-TREE"      # Name verified [Han2015]; page layout — TO VERIFY

# Items below are FROM AN UNVERIFIED SOURCE. Do not use in production code until confirmed.
HIKV_DATA_BLOCK_SIZE = 1 * 1024 * 1024 * 1024   # TO VERIFY: 1 GB data blocks
HIKV_OFNI_MARKER     = b"OFNI"                   # TO VERIFY: keyframe table marker
HIKV_OFNI_ENTRY_SIZE = 56                         # TO VERIFY: bytes per OFNI entry
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
