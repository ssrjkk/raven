"""What this machine can actually run, measured without WMIC.

Windows 11 24H2 removed the ``wmic`` CLI, so any probe built on it reports zero and the caller reads
that as "no GPU, no RAM" and quietly picks the smallest model available. Everything here uses either
a syscall or a tool that still ships: ``GlobalMemoryStatusEx``/``sysconf`` for memory, ``nvidia-smi``
for VRAM and ``shutil.disk_usage`` for the volume the weights would land on.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_GB = 1_000_000_000


@dataclass(frozen=True)
class Hardware:
    ram_total_gb: float
    ram_free_gb: float
    disk_free_gb: float
    vram_mb: int

    @property
    def cpu_only(self) -> bool:
        return self.vram_mb <= 0

    def summary(self) -> str:
        gpu = f"{self.vram_mb} MB VRAM" if self.vram_mb > 0 else "no GPU (CPU inference)"
        return f"{self.ram_free_gb:.1f} of {self.ram_total_gb:.1f} GB RAM free, {self.disk_free_gb:.1f} GB disk free, {gpu}"


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _physical_memory_bytes() -> tuple[int, int]:
    """``(total, available)`` bytes, or ``(0, 0)`` when the platform answers nothing."""
    windll = getattr(ctypes, "windll", None)
    if sys.platform == "win32" and windll is not None:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ok = windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if not ok:
            return 0, 0
        return int(status.ullTotalPhys), int(status.ullAvailPhys)
    sysconf = getattr(os, "sysconf", None)
    if sysconf is None:
        return 0, 0
    try:
        page = sysconf("SC_PAGE_SIZE")
        total = page * sysconf("SC_PHYS_PAGES")
        free = page * sysconf("SC_AVPHYS_PAGES")
    except (ValueError, OSError, KeyError):
        return 0, 0
    return int(total), int(free)


def _vram_mb() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if result.returncode != 0:
        return 0
    values = [int(line) for line in result.stdout.split() if line.isdigit()]
    return max(values) if values else 0


def weights_volume() -> Path:
    """The directory a local runtime would store model weights in, existing or not."""
    configured = os.environ.get("OLLAMA_MODELS", "")
    path = Path(configured) if configured else Path.home() / ".ollama"
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return Path.home()


def _disk_free_gb() -> float:
    """Free space on the weights volume, or 0.0 when the volume cannot be measured.

    A disconnected share or a removed drive raises here, and the other two probes already answer zero
    instead of raising. A command that only lists models must not die because one number is
    unavailable — and zero is the honest reading: the preflight concludes there is no room.
    """
    try:
        return round(shutil.disk_usage(weights_volume()).free / _GB, 2)
    except OSError:
        return 0.0


def detect() -> Hardware:
    total, free = _physical_memory_bytes()
    return Hardware(
        ram_total_gb=round(total / _GB, 2),
        ram_free_gb=round(free / _GB, 2),
        disk_free_gb=_disk_free_gb(),
        vram_mb=_vram_mb(),
    )
