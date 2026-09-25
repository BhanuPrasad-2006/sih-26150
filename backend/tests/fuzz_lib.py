"""
fuzz_lib.py — Mutation fuzzer for the disk-image parsers.

Oracle (from the BrandPlugin contract): detect / list_recordings / carve MUST NOT raise on ANY input, must finish in
bounded time, and must not blow up memory. label_all (reconstruction) must not raise on whatever the plugins return.

Seeds are valid images built from the format specs around real video; mutations are seeded and reproducible:
    Finding: (seed_name, mutation_seed, mutation_description, plugin, stage, problem)
Reproduce one with  mutate(seed_bytes, random.Random(mutation_seed)).
"""

from __future__ import annotations

import os
import random
import struct
import subprocess
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

from backend.acquisition import EvidenceImage
from backend.plugins.generic import GenericStreamPlugin
from backend.plugins.registry import PLUGINS
from backend.reconstructor import label_all

MAX_SECONDS_PER_CALL = 20.0
MAX_PEAK_MB = 400.0


@dataclass
class Finding:
    seed: str
    mutation_seed: int
    mutation: str
    plugin: str
    stage: str
    problem: str

    def __str__(self) -> str:
        return (f"[{self.seed} / mutation {self.mutation_seed}] {self.plugin}.{self.stage}: {self.problem} "
                f"({self.mutation})")


# ── Seeds ─────────────────────────────────────────────────────────────────────

def _encode(source: str, path: str) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-f", "h264", path],
        check=True,
    )
    return Path(path).read_bytes()


def build_seeds() -> dict[str, bytes]:
    """Valid images for every implemented parser, small enough to fuzz thousands of times."""
    from backend.test_images import gen_test_image as G
    from backend.tests import test_dahua_dhfs as D
    from backend.tests import test_hikvision_index as H

    tmp = Path(tempfile.mkdtemp(prefix="fuzzseed_"))
    h264 = _encode("testsrc", str(tmp / "a.h264"))
    seeds: dict[str, bytes] = {}
    seeds["dahua_frames"] = G.build_dahua_image(frames_per_channel=6)
    seeds["hikvision_master_only"] = G.build_hikvision_image()
    seeds["cpplus"] = G.build_cpplus_image() if hasattr(G, "build_cpplus_image") else b""
    base = 1_746_090_000
    dhav = D._dhav_stream(h264, 0, base)
    n = -(-len(dhav) // D._CL)
    seeds["dhfs_indexed"] = D.build_dhfs_disk([dict(camera=1, data=dhav, clusters=list(range(2, 2 + n)), t0=0)])
    entries = [_hik_entry(H, 0, 1, base, base + 10)]
    seeds["hikvision_indexed"] = H._build_indexed_image({0: _ps_wrap(h264)}, entries)
    payloads = [(h264[:2000], True), (h264[2000:4000], False), (h264[4000:6000], False)]
    hw = G.build_honeywell_stream(payloads, 1_764_193_721_896_000)
    gpt = G.build_gpt_header_image()
    gpt[40 * 512: 40 * 512 + len(hw)] = hw
    seeds["honeywell_gpt"] = bytes(gpt)
    seeds["raw_h264_in_noise"] = os.urandom(20_000) + h264 + os.urandom(20_000)
    seeds["random_noise"] = os.urandom(64 * 1024)
    return {k: v for k, v in seeds.items() if v}


def _hik_entry(H, block: int, channel: int, t0: int, t1: int) -> bytes:
    """One live HIKBTREE data-block entry, built with the test module's own encoder when present."""
    if hasattr(H, "_entry"):
        return H._entry(block, channel, t0, t1)
    e = bytearray(48)
    e[0x08:0x10] = b"\x00" * 8
    e[0x11] = channel
    struct.pack_into("<II", e, 0x18, t0, t1)
    struct.pack_into("<Q", e, 0x20, H._VIDEO_AREA + block * H._BLOCK)
    return bytes(e)


def _ps_wrap(h264: bytes) -> bytes:
    """Prefix each picture with an MPEG-PS pack header + system-map marker, as Han describes."""
    pack = b"\x00\x00\x01\xBA" + b"\x44\x00\x04\x00\x04\x01\x00\x00\x03\xF8" + b"\x00\x00\x01\xBC" + b"\x00\x06" + b"\x00" * 6
    return pack + h264


# ── Mutations ─────────────────────────────────────────────────────────────────

def hot_ranges(seed_name: str) -> list[tuple[int, int]]:
    """Byte ranges holding the fields each parser trusts (partition tables, descriptors, index entries, headers)."""
    from backend.tests import test_dahua_dhfs as D
    from backend.tests import test_hikvision_index as H
    if seed_name == "dhfs_indexed":
        return [(0, 64), (0x3C00, 0x3C00 + 256), (34 * 512, 34 * 512 + 256),
                (D._DESC_SECTOR * 512, D._DESC_SECTOR * 512 + 32 * 64)]
    if seed_name == "hikvision_indexed":
        return [(0x200, 0x300), (H._BTREE1, H._BTREE1 + 0x100 + 48 * 4), (H._BTREE2, H._BTREE2 + 0x100 + 48 * 4),
                (H._VIDEO_AREA + 4096, H._VIDEO_AREA + 4096 + 512)]
    if seed_name == "honeywell_gpt":
        return [(512, 1152), (40 * 512, 40 * 512 + 200)]
    return []


def mutate(data: bytes, rnd: random.Random, hot: list[tuple[int, int]] | None = None) -> tuple[bytes, str]:
    """Apply 1-4 random mutations; biased towards the first 64 KiB and the parser-specific hot ranges."""
    b = bytearray(data)
    notes: list[str] = []
    for _ in range(rnd.randint(1, 4)):
        kind = rnd.choice(["flip", "flip", "overwrite", "fill", "truncate", "duplicate", "insert", "u32", "zero_header"])
        n = len(b)
        if n < 16:
            break
        head = min(n, 64 * 1024)
        if hot and rnd.random() < 0.6:                         # structure-aware: hit a trusted field directly
            lo, hi = rnd.choice(hot)
            pos = min(n - 1, rnd.randrange(lo, max(lo + 1, min(hi, n))))
        else:
            pos = rnd.randrange(head) if rnd.random() < 0.7 else rnd.randrange(n)
        if kind == "flip":
            k = rnd.randint(1, 16)
            for _ in range(k):
                p = min(n - 1, pos + rnd.randrange(-8, 9)) if hot else (rnd.randrange(head) if rnd.random() < 0.7 else rnd.randrange(n))
                b[max(0, p)] ^= 1 << rnd.randrange(8)
            notes.append(f"flip{k}")
        elif kind == "overwrite":
            ln = min(rnd.randint(1, 512), n - pos)
            b[pos:pos + ln] = os.urandom(ln) if rnd.random() < 0.5 else rnd.randbytes(ln)
            notes.append(f"overwrite@{pos}+{ln}")
        elif kind == "fill":
            ln = min(rnd.choice([1, 8, 64, 512, 4096]), n - pos)
            b[pos:pos + ln] = bytes([rnd.choice([0x00, 0xFF, 0x7F, 0x80])]) * ln
            notes.append(f"fill@{pos}+{ln}")
        elif kind == "truncate":
            cut = rnd.randrange(max(1, n // 8), n)
            del b[cut:]
            notes.append(f"truncate@{cut}")
        elif kind == "duplicate":
            ln = min(rnd.randint(16, 4096), n - pos)
            b[pos:pos] = b[pos:pos + ln]
            notes.append(f"dup@{pos}+{ln}")
        elif kind == "insert":
            ln = rnd.randint(1, 64)
            b[pos:pos] = rnd.randbytes(ln)
            notes.append(f"insert@{pos}+{ln}")
        elif kind == "u32":
            if pos + 4 <= n:
                struct.pack_into("<I", b, pos, rnd.choice([0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x10000, rnd.getrandbits(32)]))
                notes.append(f"u32@{pos}")
        elif kind == "zero_header":
            ln = min(rnd.choice([16, 64, 512]), n)
            b[:ln] = b"\x00" * ln
            notes.append(f"zero_head{ln}")
    return bytes(b), ",".join(notes) or "none"


# ── Running the parsers ───────────────────────────────────────────────────────

def run_case(seed_name: str, mutation_seed: int, data: bytes, description: str, workdir: Path) -> list[Finding]:
    findings: list[Finding] = []
    path = workdir / f"case_{seed_name}_{mutation_seed}.dd"
    path.write_bytes(data)
    try:
        img = EvidenceImage.open(path)
    except Exception as exc:
        return [Finding(seed_name, mutation_seed, description, "EvidenceImage", "open", f"{type(exc).__name__}: {exc}")]
    try:
        for plugin in list(PLUGINS) + [GenericStreamPlugin()]:
            frames: list = []
            for stage in ("detect", "list_recordings", "carve"):
                tracemalloc.start()
                t0 = time.monotonic()
                try:
                    result = getattr(plugin, stage)(img)
                except Exception as exc:
                    findings.append(Finding(seed_name, mutation_seed, description, plugin.name, stage,
                                            f"raised {type(exc).__name__}: {exc}"))
                    tracemalloc.stop()
                    continue
                dt = time.monotonic() - t0
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                if dt > MAX_SECONDS_PER_CALL:
                    findings.append(Finding(seed_name, mutation_seed, description, plugin.name, stage, f"took {dt:.1f}s"))
                if peak / 1e6 > MAX_PEAK_MB:
                    findings.append(Finding(seed_name, mutation_seed, description, plugin.name, stage,
                                            f"peak Python memory {peak / 1e6:.0f} MB"))
                if stage != "detect":
                    frames += result[0] if isinstance(result, tuple) else []
                elif not (isinstance(result, float) and 0.0 <= result <= 1.0):
                    findings.append(Finding(seed_name, mutation_seed, description, plugin.name, stage,
                                            f"confidence out of range: {result!r}"))
            try:
                label_all(frames, "fuzz-evidence")
            except Exception as exc:
                findings.append(Finding(seed_name, mutation_seed, description, plugin.name, "label_all",
                                        f"raised {type(exc).__name__}: {exc}"))
    finally:
        img.close()
        try:
            path.unlink()
        except OSError:
            pass
    return findings


def fuzz(seeds: dict[str, bytes], iterations: int, base_seed: int = 0, workdir: Path | None = None) -> list[Finding]:
    workdir = workdir or Path(tempfile.mkdtemp(prefix="fuzzrun_"))
    out: list[Finding] = []
    for name, data in seeds.items():
        hot = hot_ranges(name)
        for i in range(iterations):
            ms = base_seed + i
            mutated, desc = mutate(data, random.Random(ms), hot)
            out += run_case(name, ms, mutated, desc, workdir)
    return out
