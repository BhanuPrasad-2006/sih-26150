"""The downloadable validation kit: reproducible, minimal, self-contained, and consistent with its download page."""

import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_kit_package as B  # noqa: E402


def test_zip_is_reproducible_and_small(tmp_path):
    a = B.build_zip(B.collect(), tmp_path / "a.zip")
    b = B.build_zip(B.collect(), tmp_path / "b.zip")
    assert a == b                                                                      # same sources, same bytes
    assert (tmp_path / "a.zip").stat().st_size < 3 * 1024 * 1024


def test_zip_contains_only_what_the_kit_needs(tmp_path):
    B.build_zip(B.collect(), tmp_path / "k.zip")
    names = zipfile.ZipFile(tmp_path / "k.zip").namelist()
    assert all(n.startswith("sih-validation-kit/") for n in names)
    joined = "\n".join(names)
    for forbidden in ("cv_models", ".onnx", ".env", ".key", ".pem", "tests/", "test_images", "__pycache__",
                      "backend/main.py", "backend/auth.py", "frontend", ".dd", "database"):
        assert forbidden not in joined, forbidden
    for needed in ("README_FIRST.txt", "GUIDE.md", "install_kit.bat", "run_kit.bat", "install_kit.sh", "run_kit.sh",
                   "requirements_kit.txt", "validation_notes_template.json", "backend/validation_kit.py",
                   "backend/plugins/dahua.py", "VERSION.txt"):
        assert f"sih-validation-kit/{needed}" in names, needed


def test_shell_scripts_are_executable_and_batch_files_use_windows_line_endings(tmp_path):
    B.build_zip(B.collect(), tmp_path / "k.zip")
    z = zipfile.ZipFile(tmp_path / "k.zip")
    for n in ("install_kit.sh", "run_kit.sh"):
        assert (z.getinfo(f"sih-validation-kit/{n}").external_attr >> 16) & 0o111
        assert b"\r\n" not in z.read(f"sih-validation-kit/{n}")
    for n in ("install_kit.bat", "run_kit.bat"):
        data = z.read(f"sih-validation-kit/{n}")
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_committed_zip_page_and_hash_file_agree():
    zp = ROOT / "docs" / "download" / B.ZIP_NAME
    assert zp.is_file(), "run: python tools/build_kit_package.py"
    sha = hashlib.sha256(zp.read_bytes()).hexdigest()
    assert (ROOT / "docs" / "download" / (B.ZIP_NAME + ".sha256")).read_text().startswith(sha)
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert sha in page and "{{" not in page and 'href="download/sih-validation-kit.zip"' in page
    assert (ROOT / "docs" / ".nojekyll").exists()


def test_page_loads_nothing_from_other_sites():
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    assert all(u.startswith("https://github.com/BhanuPrasad-2006/sih-26150") for u in external), external
    assert "<script" not in page and "@import" not in page


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg needed")
def test_extracted_kit_runs_with_no_web_dependencies(tmp_path):
    """Unzip the package, block every web-app dependency, and run a real validation from the extracted copy."""
    from backend.tests import test_validation_kit as T
    from backend.tests import test_dahua_dhfs as D

    B.build_zip(B.collect(), tmp_path / "k.zip")
    zipfile.ZipFile(tmp_path / "k.zip").extractall(tmp_path / "x")
    kit = tmp_path / "x" / "sih-validation-kit"

    a = D._encode("testsrc", str(tmp_path / "a.h264"))
    media = {"dhav_a": D._dhav_stream(a, 0, T.BASE)}
    before, after = T._disks(media, both=False, tmp=tmp_path)
    clip = T._remux_to_mp4(tmp_path / "a.h264", tmp_path / "clip.mp4")

    code = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "for m in ('fastapi','starlette','uvicorn','bcrypt','psycopg2','aiofiles','aiosqlite','cryptography',"
        "'pyhanko','dotenv','httpx','multipart','onnxruntime'):\n    sys.modules[m] = None\n"
        "import backend; assert backend.__file__.startswith(r'%s'), backend.__file__\n"
        "from backend.validation_kit import main\n"
        "sys.exit(main(['--after', r'%s', '--before', r'%s', '--clip', r'%s', '--out', r'%s']))\n"
        % (kit, kit, after, before, clip, tmp_path / "result")
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(kit), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "VERDICT: The recovered video matches" in r.stdout
    assert (tmp_path / "result" / "validation_report.pdf").is_file()


def test_committed_zip_is_up_to_date_with_the_sources():
    """If a module the kit ships changed, the download must be rebuilt (python tools/build_kit_package.py)."""
    committed = zipfile.ZipFile(ROOT / "docs" / "download" / B.ZIP_NAME)
    fresh = B.collect()
    fresh.pop("VERSION.txt")
    have = {n.split("/", 1)[1]: committed.read(n) for n in committed.namelist() if not n.endswith("VERSION.txt")}
    assert set(have) == set(fresh)
    stale = [n for n in fresh if fresh[n] != have[n]]
    assert not stale, f"download is out of date for {stale}: run python tools/build_kit_package.py"
