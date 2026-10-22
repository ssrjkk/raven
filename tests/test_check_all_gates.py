from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_check_all() -> Any:
    cwd = Path.cwd()
    try:
        spec = importlib.util.spec_from_file_location("check_all", ROOT / "scripts" / "check_all.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # @dataclass in the script resolves its own module through sys.modules.
        sys.modules["check_all"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(cwd)


ca = _load_check_all()


def _stub_run(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    stderr: str,
    captured: dict[str, Any],
) -> None:
    def _inner(cmd: list[str], timeout: int = 0, env: dict[str, str] | None = None, cwd: Any = None) -> Any:
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(ca, "_run", _inner)


class TestRunTimeout:
    def test_timeout_returns_a_failed_result_instead_of_raising(self) -> None:
        r = ca._run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
        assert r.returncode == ca.TIMEOUT_RETURNCODE
        assert "TIMED OUT" in r.stderr

    def test_successful_run_is_untouched(self) -> None:
        r = ca._run([sys.executable, "-c", "print('ok')"], timeout=60)
        assert r.returncode == 0
        assert "ok" in r.stdout


class TestStageReporting:
    def test_component_timeout_is_a_failed_stage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, "", "TIMED OUT after 600s (process killed)", captured)
        result = ca.check_component("core")
        assert result.status == "fail"
        assert "TIMED OUT after 600s" in result.detail

    def test_unit_batch_uses_its_configured_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "6424 passed, 22 skipped in 682.73s (0:11:22)", "", captured)
        result = ca.check_component("unit")
        assert result.status == "pass"
        assert captured["timeout"] == 1200

    def test_components_without_a_cap_keep_600s(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "169 passed in 9.54s", "", captured)
        result = ca.check_component("channels")
        assert result.status == "pass"
        assert captured["timeout"] == 600

    def test_full_suite_timeout_is_a_failed_stage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, ".....", "TIMED OUT after 1800s (process killed)", captured)
        result = ca.check_full_tests()
        assert result.status == "fail"
        assert "TIMED OUT after 1800s" in result.detail

    def test_passing_full_suite_reports_the_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "1234 passed in 900.0s (0:15:00)", "", captured)
        result = ca.check_full_tests()
        assert result.status == "pass"
        assert result.detail == "1234 passed in 900.0s (0:15:00)"
        assert captured["timeout"] == 1800

    def test_mypy_timeout_names_the_kill_instead_of_an_empty_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, "", "TIMED OUT after 300s (process killed)", captured)
        result = ca.check_mypy()
        assert result.status == "fail"
        assert "TIMED OUT after 300s" in result.detail
        assert captured["timeout"] == 300

    def test_mypy_reports_type_errors_as_usual(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 1, "raven/tools/media.py:246:24: error: Name 'foo' is not defined", "", captured)
        result = ca.check_mypy()
        assert result.status == "fail"
        assert "media.py:246" in result.detail

    def test_ruff_timeout_names_the_kill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, "", "TIMED OUT after 120s (process killed)", captured)
        result = ca.check_ruff()
        assert result.status == "fail"
        assert "TIMED OUT after 120s" in result.detail
