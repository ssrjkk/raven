"""The gate has to be able to say "not the tree".

Gate #2 printed five `[FAIL]` stages — mypy, tests/full, tests/core, tests/unit and the frontend's
`npm ci` — and reading them as verdicts about the code sent the investigation after a type error, a
retention test and an RSS test that were all fine. The tree had 8.5 GB of commit charge stolen from it by
log tailers left attached to finished runs, and what a starved Windows box reports for that is
`OSError: [WinError 1450] Недостаточно системных ресурсов` on a rename, `[Errno 22] Invalid argument` on an
open of a path that is perfectly valid, and a V8 heap-death notice from npm — none of which names memory.

So the machine is measured as its own stage before the code is judged, and a stage that fails with one of
those signatures says so with the numbers read at that moment. Both halves need proofs: the guard must
fire on a starved box, and it must stay silent on a real failure, or it becomes a way of explaining away
anything the gate finds.
"""

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
        spec = importlib.util.spec_from_file_location("check_all_env", ROOT / "scripts" / "check_all.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # @dataclass in the script resolves its own module through sys.modules.
        sys.modules["check_all_env"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(cwd)


ca = _load_check_all()

# Verbatim from the run this guard exists for: pytest's own reporting phase dying, in the middle of a stage
# that then reported "3 failed, 6872 passed" as though the three were the interesting part.
STARVED_PYTEST_OUTPUT = """
  INTERNALERROR>   File "C:\\...\\allure_commons\\logger.py", line 29, in _report_item
  INTERNALERROR>     with io.open(tmp_filepath, "w", encoding="utf8") as json_file:
  INTERNALERROR> OSError: [Errno 22] Invalid argument: 'D:\\\\Dev\\\\Temp\\\\x\\\\allure-results\\\\5-result.json.tmp'
  INTERNALERROR>   File "C:\\...\\allure_commons\\logger.py", line 32, in _report_item
  INTERNALERROR>     os.replace(tmp_filepath, final_filepath)
  INTERNALERROR> OSError: [WinError 1450] Недостаточно системных ресурсов для завершения операции
  3 failed, 6872 passed, 37 skipped in 1076.45s (0:17:56)
"""

NPM_HEAP_DEATH = """
<--- Last few GCs --->
[20384:00000238A48F6000]     4087 ms: Mark-Compact 49.2 (99.4) -> 37.1 (103.4) MB
FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
"""

ORDINARY_CODE_FAILURE = """
tests/core/test_retention.py::test_a_policy_ages_its_own_table FAILED
E   assert 3 == 2
E    +  where 3 = len([Row(a=1), Row(a=2), Row(a=3)])
1 failed, 20 passed in 4.21s
"""


def test_the_gate_measures_the_machine_it_is_running_on() -> None:
    """A stage that always passes is worse than no stage: it makes the next reader trust a number nobody took."""
    result = ca.check_environment()
    assert result.name == "environment"
    assert "commit=" in result.detail and "disk=" in result.detail, result.detail
    assert any(char.isdigit() for char in result.detail), f"no reading in {result.detail!r}"
    if result.status == "pass":
        assert "reporter wrote" in result.detail, result.detail


def test_the_starved_readings_fail_the_environment_stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The exact numbers gate #2 ran under: 670 MB of free commit on a box with a 20 GB ceiling."""
    monkeypatch.setattr(ca, "ROOT", tmp_path)
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 670.0)
    result = ca.check_environment()
    assert result.status == "fail"
    assert "commit charge free" in result.detail, result.detail
    assert "670" in result.detail, result.detail


def test_the_reporter_probe_writes_and_renames_for_real(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The probe is only evidence if it does the two operations the starved run died on, in the directory the
    reporter uses. Its own files are its own to clean up."""
    monkeypatch.setattr(ca, "ROOT", tmp_path)
    ca._probe_reporter_writes()
    results = tmp_path / "allure-results"
    assert results.is_dir()
    assert not list(results.glob("capacity-probe-*")), "the probe left its files in the reporter's directory"


def test_a_reporter_that_cannot_write_fails_the_stage_even_with_memory_to_spare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counters were never the point — the rename inside the reporter is what broke. A box can pass every
    number and still not be able to record a run, and that has to stop the gate rather than mid-way through it."""

    def _refuse() -> None:
        raise OSError(22, "Invalid argument", "allure-results/5-result.json.tmp")

    monkeypatch.setattr(ca, "free_commit_mb", lambda: 8000.0)
    monkeypatch.setattr(ca, "_probe_reporter_writes", _refuse)
    result = ca.check_environment()
    assert result.status == "fail"
    assert "cannot write and rename its own results" in result.detail, result.detail


def test_free_disk_below_the_floor_fails_the_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    monkeypatch.setattr(ca, "free_commit_mb", lambda: 8000.0)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil_usage(900 * 1024 * 1024))
    result = ca.check_environment()
    assert result.status == "fail"
    assert "volume holding the tree" in result.detail, result.detail


def shutil_usage(free: int) -> Any:
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    return Usage(100 * 1024**3, 100 * 1024**3 - free, free)


def test_a_commit_reading_of_unknown_is_not_a_pass_and_not_a_lie(monkeypatch: pytest.MonkeyPatch) -> None:
    """A platform this probe cannot read reports `unknown` and is judged on what it can measure. Silence would
    look like a green stage; a failure would be a false one on every macOS box that tries the gate."""
    monkeypatch.setattr(ca, "free_commit_mb", lambda: None)
    result = ca.check_environment()
    assert "commit=unknown" in result.detail, result.detail
    assert "commit charge" not in result.detail, result.detail


def test_the_starved_pytest_run_is_named_as_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 670.0)
    note = ca._starvation_note(STARVED_PYTEST_OUTPUT)
    assert note.startswith("ENVIRONMENT:"), note
    assert "ERROR_NO_SYSTEM_RESOURCES" in note, note
    assert "the reporter could not open a result file" in note, note
    assert "670 MB" in note, "the note has to carry the reading that explains it"


def test_the_npm_heap_death_is_named_as_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """`frontend npm ci` was the fifth false failure of gate #2, and its output never mentions memory either."""
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 512.0)
    note = ca._starvation_note(NPM_HEAP_DEATH)
    assert "V8" in note and "512 MB" in note, note


def test_an_ordinary_test_failure_is_not_blamed_on_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole reason this guard is allowed to exist: a real assertion must stay a real assertion at full
    commit pressure, or the stage becomes an excuse for every red the gate ever prints."""
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 300.0)
    assert ca._starvation_note(ORDINARY_CODE_FAILURE) == ""


def test_a_starved_component_stage_carries_the_note_in_its_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard has to reach the log line a person reads, which is the stage detail, not a helper nobody calls."""

    def _inner(cmd: list[str], timeout: int = 0, env: dict[str, str] | None = None, cwd: Any = None) -> Any:
        return subprocess.CompletedProcess(cmd, 2, stdout=STARVED_PYTEST_OUTPUT, stderr="")

    monkeypatch.setattr(ca, "_run", _inner)
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 670.0)
    result = ca.check_component("channels")
    assert result.status == "fail"
    assert "ENVIRONMENT:" in result.detail, result.detail


def test_a_starved_full_stage_carries_the_note_in_its_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _inner(cmd: list[str], timeout: int = 0, env: dict[str, str] | None = None, cwd: Any = None) -> Any:
        return subprocess.CompletedProcess(cmd, 3, stdout=STARVED_PYTEST_OUTPUT, stderr="")

    monkeypatch.setattr(ca, "_run", _inner)
    monkeypatch.setattr(ca, "free_commit_mb", lambda: 670.0)
    result = ca.check_full_tests()
    assert result.status == "fail"
    assert "ENVIRONMENT:" in result.detail, result.detail


def test_the_environment_stage_runs_before_any_verdict_is_printed() -> None:
    """A reader who reaches the summary after a 30-minute run must not have to wonder whether the box held it."""
    source = (ROOT / "scripts" / "check_all.py").read_text(encoding="utf-8")
    main_body = source[source.index("def main() -> int:") :]
    assert main_body.index("check_environment()") < main_body.index("check_ruff()"), main_body[:400]
