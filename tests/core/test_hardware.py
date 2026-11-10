"""The hardware probe behind ``raven setup`` and the bundled model preflight.

These tests exist because ``wmic`` is gone from current Windows builds and every probe built on it
answers zero. A zero is not an error to the caller: it reads as "no GPU, little RAM" and the
onboarding quietly picks the smallest model, so a broken probe looks exactly like a small machine.
"""

from __future__ import annotations

import ctypes
import os
import pathlib
import shutil as _shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from raven.core import hardware
from raven.core.hardware import Hardware

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _run(stdout: str = "", returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


class TestPhysicalMemory:
    def test_this_machine_answers_with_real_numbers(self) -> None:
        total, free = hardware._physical_memory_bytes()
        assert total > 0, "memory probe returned zero — indistinguishable from a machine with no RAM"
        assert 0 <= free <= total

    def test_sysconf_without_a_platform_answer_is_zero_not_an_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(ctypes, "windll", None, raising=False)

        def _boom(_name: str) -> int:
            raise ValueError("no sysconf here")

        monkeypatch.setattr(os, "sysconf", _boom, raising=False)
        assert hardware._physical_memory_bytes() == (0, 0)


class TestVram:
    def test_highest_gpu_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _run("24576\n8192\n"))
        assert hardware._vram_mb() == 24576

    def test_failing_query_is_no_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _run("", returncode=1))
        assert hardware._vram_mb() == 0

    def test_absent_binary_is_no_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _missing(*_a: object, **_k: object) -> SimpleNamespace:
            raise FileNotFoundError("nvidia-smi")

        monkeypatch.setattr(subprocess, "run", _missing)
        assert hardware._vram_mb() == 0

    def test_non_numeric_output_is_no_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _run("[N/A]\n"))
        assert hardware._vram_mb() == 0


class TestWeightsVolume:
    def test_configured_directory_is_used(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        models = tmp_path / "models"
        models.mkdir()
        monkeypatch.setenv("OLLAMA_MODELS", str(models))
        assert hardware.weights_volume() == models

    def test_nearest_existing_ancestor_of_a_not_yet_created_path(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "nested" / "deeper"))
        assert hardware.weights_volume() == tmp_path

    def test_default_is_the_user_ollama_directory(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OLLAMA_MODELS", raising=False)
        fake_home = tmp_path / "user"
        (fake_home / ".ollama").mkdir(parents=True)
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: fake_home))
        assert hardware.weights_volume() == fake_home / ".ollama"

    def test_default_walks_up_to_home_when_the_ollama_directory_is_absent(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OLLAMA_MODELS", raising=False)
        fake_home = tmp_path / "user"
        fake_home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: fake_home))
        assert hardware.weights_volume() == fake_home

def test_no_wmic_argv_anywhere_in_shipped_code() -> None:
    """``wmic`` left Windows; a probe that calls it returns zero, and zero reads as a small machine.

    Only the argv spellings are matched, so this file's own prose about the removal stays put.
    """
    quoted = ('"wmic', "'wmic")
    offenders: list[str] = []
    for directory in ("raven", "ravencode", "aios", "scripts", "web/src", "extension"):
        for path in (ROOT / directory).rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".ps1", ".sh"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in quoted):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"wmic-based probes always answer zero: {offenders}"


class TestHardware:
    def test_cpu_only_when_nothing_can_offload(self) -> None:
        assert Hardware(16.0, 12.0, 100.0, 0).cpu_only is True
        assert Hardware(16.0, 12.0, 100.0, 8192).cpu_only is False

    def test_summary_states_every_number_it_measured(self) -> None:
        read = Hardware(ram_total_gb=8.4, ram_free_gb=0.9, disk_free_gb=59.0, vram_mb=0)
        assert read.summary() == "0.9 of 8.4 GB RAM free, 59.0 GB disk free, no GPU (CPU inference)"
        gpu = Hardware(ram_total_gb=32.0, ram_free_gb=24.0, disk_free_gb=500.0, vram_mb=12288)
        assert gpu.summary() == "24.0 of 32.0 GB RAM free, 500.0 GB disk free, 12288 MB VRAM"


class TestDetect:
    @pytest.fixture(autouse=True)
    def _probes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardware, "_physical_memory_bytes", lambda: (8_589_934_592, 966_367_692))
        monkeypatch.setattr(hardware, "_vram_mb", lambda: 0)
        monkeypatch.setattr(hardware, "weights_volume", lambda: pathlib.Path("C:/fake"))
        monkeypatch.setattr(
            _shutil, "disk_usage", lambda _p: SimpleNamespace(total=0, used=0, free=59_000_000_000)
        )

    def test_rounds_each_resource_into_gigabytes(self) -> None:
        read = hardware.detect()
        assert read == Hardware(ram_total_gb=8.59, ram_free_gb=0.97, disk_free_gb=59.0, vram_mb=0)

    def test_an_unmeasurable_volume_is_zero_not_an_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A disconnected share raises; `raven models list` must still print, and zero means no room."""

        def _gone(_path: object) -> SimpleNamespace:
            raise OSError("the network name is no longer available")

        monkeypatch.setattr(_shutil, "disk_usage", _gone)
        read = hardware.detect()
        assert read.disk_free_gb == 0.0
        assert read.ram_total_gb == 8.59, "one unmeasurable resource may not zero the others"


def test_disk_usage_measures_the_volume_the_weights_land_on(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(hardware, "weights_volume", lambda: tmp_path)
    monkeypatch.setattr(hardware, "_vram_mb", lambda: 0)
    read = hardware.detect()
    assert read.disk_free_gb == round(_shutil.disk_usage(tmp_path).free / hardware._GB, 2)


def test_subprocess_run_is_called_with_a_list_not_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shell string would let a path with spaces become command injection in the probe."""
    calls: list[object] = []

    def _record(cmd: object, *a: object, **k: object) -> SimpleNamespace:
        calls.append(cmd)
        return _run("", returncode=1)

    monkeypatch.setattr(subprocess, "run", _record)
    hardware._vram_mb()
    assert calls and isinstance(calls[0], list)
