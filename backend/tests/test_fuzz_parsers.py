"""Mutation-fuzz the disk-image parsers. The plugin contract says detect / list_recordings / carve never raise
and finish in bounded time on ANY input; this checks that on a reproducible batch of corrupted images.
Long runs: python backend/tests/manual/fuzz_parsers.py 2000"""

import shutil
import subprocess

import pytest

from backend.tests import fuzz_lib as F

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg needed to build seed images")

ITERATIONS = 25          # per seed; ~10 seconds in total


@pytest.fixture(scope="module")
def seeds():
    return F.build_seeds()


def test_seeds_cover_every_implemented_parser(seeds):
    assert {"dahua_frames", "dhfs_indexed", "hikvision_indexed", "honeywell_gpt", "raw_h264_in_noise",
            "random_noise"} <= set(seeds)


def test_parsers_survive_mutated_images(seeds, tmp_path):
    findings = F.fuzz(seeds, ITERATIONS, base_seed=1000, workdir=tmp_path)
    assert not findings, "parser contract violated:\n" + "\n".join(str(f) for f in findings[:10])


def test_parsers_survive_targeted_field_corruption(seeds, tmp_path):
    """Corrupt exactly the fields the parsers trust (partition table, descriptors, index entries)."""
    import random
    findings = []
    for name in ("dhfs_indexed", "hikvision_indexed", "honeywell_gpt"):
        hot = F.hot_ranges(name)
        for i in range(40):
            data, desc = F.mutate(seeds[name], random.Random(50_000 + i), hot)
            findings += F.run_case(name, 50_000 + i, data, desc, tmp_path)
    assert not findings, "\n".join(str(f) for f in findings[:10])


def test_fuzzer_actually_detects_a_raising_plugin(seeds, tmp_path, monkeypatch):
    """Oracle self-test: if a parser did raise, the harness must report it."""
    class Broken:
        name = "broken"
        def detect(self, img): return 0.0
        def list_recordings(self, img): return [], ""
        def carve(self, img, progress_cb=None): raise ValueError("boom")
    monkeypatch.setattr(F, "PLUGINS", [Broken()])
    f = F.run_case("random_noise", 1, seeds["random_noise"], "none", tmp_path)
    assert any(x.plugin == "broken" and "boom" in x.problem for x in f)


def test_fuzzer_detects_a_slow_plugin_and_bad_confidence(seeds, tmp_path, monkeypatch):
    import time
    class Slow:
        name = "slow"
        def detect(self, img): return 7.0                     # out of range
        def list_recordings(self, img): time.sleep(0.2); return [], ""
        def carve(self, img, progress_cb=None): return [], ""
    monkeypatch.setattr(F, "PLUGINS", [Slow()])
    monkeypatch.setattr(F, "MAX_SECONDS_PER_CALL", 0.05)
    problems = [x.problem for x in F.run_case("random_noise", 2, seeds["random_noise"], "none", tmp_path)]
    assert any("took" in p for p in problems) and any("confidence out of range" in p for p in problems)
