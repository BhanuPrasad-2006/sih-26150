"""
sandbox.py — Run external media tools (ffmpeg / ffprobe) with hard resource limits and no secrets.

Why: carved video and examiner-supplied ground-truth files are UNTRUSTED input to a large C parser. The limits keep
a malformed file from exhausting the machine, and the scrubbed environment keeps a compromised child from reading
database credentials or keys out of its environment.

What it enforces
  - wall-clock timeout, then the whole process is killed
  - memory cap (Windows: Job Object process-memory limit; Linux/macOS: RLIMIT_AS)
  - Windows: at most one process in the job (the tool cannot spawn children), killed if the tool exits
  - Linux/macOS: CPU-seconds and output-size limits, no core dumps, own session
  - environment scrubbed of anything that looks like a secret
  - ffmpeg/ffprobe argument helpers that disable every protocol except local files and pipes
    (blocks playlist / concat tricks that would make ffmpeg open URLs or read other local files by name)

What it does NOT do: it is not a container. It does not restrict which files the process can read, or the network.
For stronger isolation run the tool in a VM / container / separate low-privilege account.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Optional

DEFAULT_MEM_MB = 2048
FFMPEG_SAFE_INPUT = ["-protocol_whitelist", "file,pipe"]      # must precede the -i / input file
_SECRET_NAME = re.compile(r"(PASS|SECRET|TOKEN|KEY|CREDENTIAL|DATABASE_URL|AUTH|COOKIE)", re.I)


def scrubbed_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not _SECRET_NAME.search(k) and not k.startswith("SIH_")}


# ── Windows job object ────────────────────────────────────────────────────────

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectExtendedLimitInformation = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _EXT_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _make_job(mem_mb: int):
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = (_JOB_OBJECT_LIMIT_PROCESS_MEMORY |
                                                 _JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
                                                 _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = mem_mb * 1024 * 1024
        if not _k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation, ctypes.byref(info),
                                            ctypes.sizeof(info)):
            _k32.CloseHandle(job)
            return None
        return job


def _posix_preexec(mem_mb: int, cpu_seconds: int, max_file_mb: int):
    def apply():
        import resource
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_mb * 1024 * 1024,) * 2)
    return apply


def run_limited(
    cmd: list[str],
    *,
    timeout: int,
    mem_mb: int = DEFAULT_MEM_MB,
    max_file_mb: int = 16 * 1024,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Like subprocess.run(capture_output=True) with the limits above. Raises subprocess.TimeoutExpired after
    killing the process when `timeout` seconds pass. A process killed for exceeding memory returns a non-zero code.
    """
    kwargs: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env=scrubbed_env(), text=text)
    job = None
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["preexec_fn"] = _posix_preexec(mem_mb, timeout + 30, max_file_mb)

    proc = subprocess.Popen(cmd, **kwargs)
    if os.name == "nt":
        job = _make_job(mem_mb)
        if job:
            _k32.AssignProcessToJobObject(job, int(proc._handle))    # small race window before assignment
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        if job:
            _k32.CloseHandle(job)                                    # KILL_ON_JOB_CLOSE: nothing outlives us
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
