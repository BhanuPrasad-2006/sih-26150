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
HIKV_NAL_PREFIX_0xBA = 0xBA                       # TO VERIFY: firmware variant A prefix
HIKV_NAL_PREFIX_0xBC = 0xBC                       # TO VERIFY: firmware variant B prefix

# Standard H.264/H.265 NAL start code (used in carving — many false positives expected)
HIKV_NAL_START_CODE = b"\x00\x00\x00\x01"        # Verified: H.264/H.265 standard

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
