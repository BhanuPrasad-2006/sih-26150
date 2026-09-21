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

# Frame start and end markers
DHAV_HEADER_MAGIC = b"DHAV"          # Verified [MDPI2025, FFmpeg-dhav]
DHAV_FOOTER_MAGIC = b"dhav"          # Verified [MDPI2025, FFmpeg-dhav]

# Header layout (all fields little-endian)
DHAV_HEADER_SIZE = 0x28              # 40 bytes — Verified [FFmpeg-dhav]
DHAV_FOOTER_SIZE = 8                 # 4 (magic) + 4 (length) — Verified [FFmpeg-dhav]

# Field offsets within the 40-byte header
DHAV_OFF_FRAME_TYPE   = 0x04        # uint8  — Verified [FFmpeg-dhav]
DHAV_OFF_SUBTYPE      = 0x05        # uint8  — meaning unknown — Verified field exists [FFmpeg-dhav]
DHAV_OFF_CHANNEL      = 0x06        # uint16 LE — Verified [FFmpeg-dhav]
DHAV_OFF_SEQUENCE     = 0x08        # uint32 LE — Verified [FFmpeg-dhav]
DHAV_OFF_TOTAL_SIZE   = 0x0C        # uint32 LE (header + payload + footer) — Verified [FFmpeg-dhav]
DHAV_OFF_TIMESTAMP_S  = 0x10        # uint32 LE (seconds, Unix-like epoch) — Verified [FFmpeg-dhav]
DHAV_OFF_TIMESTAMP_MS = 0x14        # uint16 LE (milliseconds 0–999) — Verified [FFmpeg-dhav]
# Bytes 0x16–0x27: unknown fields — TO VERIFY

# Footer layout: at position (frame_start + total_size - DHAV_FOOTER_SIZE)
DHAV_FOOTER_OFF_MAGIC  = 0          # 4 bytes: b"dhav" — Verified [FFmpeg-dhav]
DHAV_FOOTER_OFF_LENGTH = 4          # uint32 LE: same value as DHAV_OFF_TOTAL_SIZE — Verified [FFmpeg-dhav]

# Valid frame type bytes
DHAV_TYPE_VIDEO_IFRAME = 0xF0       # Video keyframe (I-frame) — Verified [FFmpeg-dhav]
DHAV_TYPE_VIDEO_PFRAME = 0xF1       # Video delta frame (P/B) — Verified [FFmpeg-dhav]
DHAV_TYPE_AUDIO_FC     = 0xFC       # Audio — Verified [FFmpeg-dhav]
DHAV_TYPE_AUDIO_FD     = 0xFD       # Audio (variant) — Verified [FFmpeg-dhav]
DHAV_VALID_FRAME_TYPES = frozenset({
    DHAV_TYPE_VIDEO_IFRAME,
    DHAV_TYPE_VIDEO_PFRAME,
    DHAV_TYPE_AUDIO_FC,
    DHAV_TYPE_AUDIO_FD,
})

# Frame length plausibility bounds (proposed — tune on real data)
DHAV_MIN_FRAME_BYTES = 100          # Proposed — smaller is almost certainly a false positive
DHAV_MAX_FRAME_BYTES = 10 * 1024 * 1024  # Proposed — 10 MB upper bound

# Channel number plausibility
DHAV_MAX_CHANNEL = 31               # 0-based; analog DVRs carry up to 32 channels — [MDPI2026]

# Timestamp sanity epoch bounds (Unix seconds)
# Reject clocks that were never set (year 2000 = 946684800) and future timestamps
DHAV_TS_MIN_UNIX = 946684800        # 2000-01-01 00:00:00 UTC — Proposed
# DHAV_TS_MAX_UNIX computed at runtime as int(time.time()) + 86400

# Sequence continuity: gap larger than this → start a new segment
DHAV_SEQ_GAP_THRESHOLD = 3          # Proposed [PRD §5.6.1]

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
