"""
test_desktop_app.py — the bundled-ffmpeg PATH fallback used by the frozen Windows installer.

backend/desktop_app.py is not imported by the rest of the test suite (it starts a real server
thread and a real GUI window in main()), so this only imports the module — it never calls main().
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

import pytest


@pytest.fixture()
def desktop_app_module():
    """A fresh import of backend/desktop_app.py, isolated from whatever else already imported it."""
    spec = importlib.util.spec_from_file_location("desktop_app_under_test", "backend/desktop_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ffmpeg_already_on_path_is_left_alone(desktop_app_module):
    before = os.environ.get("PATH", "")
    with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        desktop_app_module._ensure_ffmpeg_on_path()
    assert os.environ.get("PATH", "") == before


def test_bundled_ffmpeg_is_added_to_path_when_missing(desktop_app_module):
    """
    Simulates a frozen PyInstaller build (sys._MEIPASS) shipping ffmpeg alongside the app, on a
    machine with no ffmpeg on PATH — the exact situation this exists for.

    Creates both possible binary names (ffmpeg.exe and ffmpeg) so this test passes regardless of
    which OS actually runs it, and deliberately does NOT mock os.name to force one branch: on
    Python 3.12+, pathlib.Path() itself dispatches to WindowsPath/PosixPath based on the REAL
    os.name at construction time, so mocking it to "nt" on a Linux CI runner makes the very first
    Path(...) call raise NotImplementedError, before this function's own os.name check is ever
    reached. This actually happened once in CI (Linux) after a change that passed locally
    (Windows) — this comment is here so it is not reintroduced.
    """
    bundle = Path(tempfile.mkdtemp())
    (bundle / "ffmpeg").mkdir()
    (bundle / "ffmpeg" / "ffmpeg.exe").write_text("fake")
    (bundle / "ffmpeg" / "ffmpeg").write_text("fake")
    before = os.environ.get("PATH", "")
    try:
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(desktop_app_module.sys, "_MEIPASS", str(bundle), create=True):
            desktop_app_module._ensure_ffmpeg_on_path()
        assert str(bundle / "ffmpeg") in os.environ.get("PATH", "")
    finally:
        os.environ["PATH"] = before
        shutil.rmtree(bundle, ignore_errors=True)


def test_no_ffmpeg_anywhere_leaves_path_unchanged(desktop_app_module):
    """Neither on PATH nor bundled (e.g. a dev checkout with no fetch_ffmpeg.py run and no
    system ffmpeg) — must not crash, and must not invent a nonexistent directory on PATH.
    Path.is_file is mocked False so this holds even on this dev machine, which does have a real
    packaging/vendor/ffmpeg/ (fetched separately for the installer build)."""
    before = os.environ.get("PATH", "")
    try:
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(desktop_app_module.sys, "_MEIPASS", None, create=True), \
             mock.patch.object(Path, "is_file", return_value=False):
            desktop_app_module._ensure_ffmpeg_on_path()
        assert os.environ.get("PATH", "") == before
    finally:
        os.environ["PATH"] = before
