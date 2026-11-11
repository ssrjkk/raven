from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
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
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(ca, "_run", _inner)


def _full_stage_command(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> list[str]:
    def _inner(cmd: list[str], timeout: int = 0, env: dict[str, str] | None = None, cwd: object = None) -> object:
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="7020 passed in 900s", stderr="")

    monkeypatch.setattr(ca, "_run", _inner)
    ca.check_full_tests()
    return list(captured["cmd"])


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
    def test_component_timeout_is_a_failed_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        # the point is that the stage honours its own configured cap, not what the number is today
        assert captured["timeout"] == ca.COMPONENTS["unit"]["timeout"]

    def test_components_without_a_cap_keep_600s(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "169 passed in 9.54s", "", captured)
        result = ca.check_component("channels")
        assert result.status == "pass"
        assert captured["timeout"] == 600

    def test_full_suite_timeout_is_a_failed_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, ".....", "TIMED OUT after 1800s (process killed)", captured)
        result = ca.check_full_tests()
        assert result.status == "fail"
        assert "TIMED OUT after 1800s" in result.detail

    def test_passing_full_suite_reports_the_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "1234 passed in 900.0s (0:15:00)", "", captured)
        result = ca.check_full_tests()
        assert result.status == "pass"
        assert result.detail == "1234 passed in 900.0s (0:15:00)"
        assert captured["timeout"] == 1800

    def test_mypy_timeout_names_the_kill_instead_of_an_empty_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, "", "TIMED OUT after 300s (process killed)", captured)
        result = ca.check_mypy()
        assert result.status == "fail"
        assert "TIMED OUT after 300s" in result.detail
        assert captured["timeout"] == 300

    def test_mypy_reports_type_errors_as_usual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 1, "raven/tools/media.py:246:24: error: Name 'foo' is not defined", "", captured)
        result = ca.check_mypy()
        assert result.status == "fail"
        assert "media.py:246" in result.detail

    def test_ruff_timeout_names_the_kill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, ca.TIMEOUT_RETURNCODE, "", "TIMED OUT after 120s (process killed)", captured)
        result = ca.check_ruff()
        assert result.status == "fail"
        assert "TIMED OUT after 120s" in result.detail


class TestStageFailureDetail:
    """A stage that dies without printing a pytest summary used to report an empty detail."""

    def test_the_tail_of_the_run_stands_in_for_a_missing_summary(self) -> None:
        output = "collected 7020 items" + chr(10) + "    return statistics.median(self.data)" + chr(10) + "MemoryError"
        detail = ca._failure_detail("", output, 1, "")
        assert "MemoryError" in detail, detail
        assert "median" in detail, detail

    def test_a_real_summary_line_is_still_the_detail(self) -> None:
        assert ca._failure_detail("1 failed, 7019 passed in 9s", "noise", 1, "") == "1 failed, 7019 passed in 9s"

    def test_a_timeout_reports_stderr_rather_than_output(self) -> None:
        assert ca._failure_detail("", "some output", ca.TIMEOUT_RETURNCODE, "TIMED OUT after 1800s") == (
            "TIMED OUT after 1800s"
        )

    def test_no_output_at_all_is_still_explained(self) -> None:
        assert ca._failure_detail("", "", 3, "") == "exit code 3, no output captured"


class TestBenchmarkIsMeasuredOnce:
    """pytest-benchmark keeps every round of every benchmarked test and computes its stats when
    the session ends; doing that twice in one gate run is what raised MemoryError on an 8 GB box.
    The timing belongs to the `unit` stage, which runs tests/benchmarks for real."""

    def test_the_full_stage_disables_the_benchmark_harness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        _stub_run(monkeypatch, 0, "7020 passed in 900s" + chr(10), "", captured)
        cmd = _full_stage_command(monkeypatch, captured)
        assert "--benchmark-disable" in cmd, cmd

    def test_the_unit_stage_still_times_the_benchmarks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "6984 passed in 700s" + chr(10), "", captured)
        result = ca.check_component("unit")
        assert result.status == "pass"
        cmd = captured["cmd"]
        assert "--benchmark-disable" not in cmd, cmd
        assert "tests/" in cmd, cmd


class TestFormatStage:
    """`docs/development.md` tells a contributor to install hooks that run `ruff format`, and no hook
    was installed and no CI job ran the formatter: measured before this stage existed, 346 of the 925
    Python files were not formatted. The stage is the control; these tests are its calibration."""

    def test_a_formatted_tree_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "925 files already formatted" + chr(10), "", captured)
        result = ca.check_format()
        assert result.status == "pass"
        assert result.detail == "925 files already formatted"

    def test_an_unformatted_file_fails_and_is_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        out = "Would reformat: raven/core/x.py" + chr(10) + "Would reformat: tests/test_x.py" + chr(10)
        _stub_run(monkeypatch, 1, out, "", captured)
        result = ca.check_format()
        assert result.status == "fail"
        assert result.counts["files"] == 2
        assert "raven/core/x.py" in result.detail
        assert "Would reformat" not in result.detail

    def test_the_same_directories_the_linter_checks_are_formatted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 0, "925 files already formatted", "", captured)
        ca.check_format()
        cmd = captured["cmd"]
        assert cmd[:4] == [sys.executable, "-m", "ruff", "format"]
        assert "--check" in cmd
        assert set(ca.CHECK_DIRS) <= set(cmd), cmd

    def test_no_formatter_installed_is_a_failure_and_not_a_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_run(monkeypatch, 1, "", "No module named ruff", captured)
        result = ca.check_format()
        assert result.status == "fail"
        assert "No module named ruff" in result.detail

    def test_the_shipped_tree_is_formatted(self) -> None:
        """The one assertion that makes the declared control real: the tree the gate ships in."""
        result = ca.check_format()
        assert result.status == "pass", result.detail


class TestAnnotationRatchet:
    """The mandate is the first line of `agents.md` — "type hints required for all Python functions" —
    and mypy ran strict with `disallow_untyped_defs = false`, so nothing measured it. The ratchet holds
    the ceiling per file, and it has to bite in both directions: debt added is refused, and a ceiling
    left above the debt it covers would let the next unannotated function in for free."""

    @staticmethod
    def _tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
        pkg = tmp_path / "raven"
        pkg.mkdir(parents=True)
        (pkg / "x.py").write_text(source, encoding="utf-8")
        monkeypatch.setattr(ca, "ROOT", tmp_path)
        monkeypatch.setattr(ca, "BANDIT_DIRS", ["raven"])

    def test_a_function_with_no_hints_at_all_is_one_hit_with_no_gaps_left_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._tree(tmp_path, monkeypatch, "def handle(request, timeout=5):\n    return 1\n")
        hits = ca._untyped_definitions()["raven/x.py"]
        assert hits == ["raven/x.py:1 handle(request, timeout, return)"]

    def test_an_annotated_function_is_not_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._tree(tmp_path, monkeypatch, "def handle(request: dict[str, str]) -> int:\n    return 1\n")
        assert ca._untyped_definitions() == {}

    def test_the_self_receiver_is_free_and_var_args_are_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`self` is implicit, and demanding a hint for it would report every method in the tree as
        unannotated. `*args` / `**kwargs` are not free: a probe file showed mypy reports them, and four
        shipped functions stayed invisible to this rule until it counted them too."""
        self._tree(
            tmp_path,
            monkeypatch,
            "class C:\n"
            "    def method(self) -> None:\n"
            "        pass\n"
            "\n"
            "    def collect(*args, **kwargs) -> None:\n"
            "        pass\n",
        )
        assert ca._untyped_definitions()["raven/x.py"] == ["raven/x.py:5 collect(*args, **kwargs)"]

    def test_a_method_that_forgets_its_return_is_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._tree(tmp_path, monkeypatch, "class C:\n    def __init__(self):\n        pass\n")
        assert ca._untyped_definitions()["raven/x.py"] == ["raven/x.py:2 __init__(return)"]

    def test_a_nested_function_is_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._tree(
            tmp_path,
            monkeypatch,
            "def outer() -> None:\n    def inner():\n        pass\n    inner()\n",
        )
        assert ca._untyped_definitions()["raven/x.py"] == ["raven/x.py:2 inner(return)"]

    @staticmethod
    def _ceiling(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        measured: dict[str, list[str]],
        ceiling: dict[str, int] | None,
    ) -> Any:
        monkeypatch.setattr(ca, "_untyped_definitions", lambda: measured)
        path = tmp_path / "untyped_baseline.json"
        if ceiling is not None:
            path.write_text(json.dumps(ceiling), encoding="utf-8")
        monkeypatch.setattr(ca, "ANNOTATION_BASELINE", path)
        return ca.check_annotations()

    def test_one_more_unannotated_function_than_the_ceiling_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._ceiling(
            monkeypatch,
            tmp_path,
            {"raven/core/new.py": ["raven/core/new.py:7 handle()", "raven/core/new.py:9 save()"]},
            {"raven/core/new.py": 1},
        )
        assert result.status == "fail"
        assert "added" in result.detail
        assert "new.py:9 save" in result.detail

    def test_a_clean_file_that_gains_one_unannotated_function_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file with no entry has a ceiling of zero, which is the whole point of the ratchet."""
        result = self._ceiling(monkeypatch, tmp_path, {"raven/core/fresh.py": ["raven/core/fresh.py:1 f()"]}, {})
        assert result.status == "fail"

    def test_a_ceiling_left_above_the_debt_it_covers_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._ceiling(
            monkeypatch, tmp_path, {"raven/core/x.py": ["raven/core/x.py:1 f()"]}, {"raven/core/x.py": 4}
        )
        assert result.status == "fail"
        assert "--annotations" in result.detail

    def test_a_file_fixed_to_clean_still_has_its_entry_removed_by_re_measuring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._ceiling(monkeypatch, tmp_path, {}, {"raven/core/x.py": 3})
        assert result.status == "fail"
        assert "raven/core/x.py" in result.detail

    def test_a_missing_ceiling_file_checks_nothing_and_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._ceiling(monkeypatch, tmp_path, {}, None)
        assert result.status == "fail"
        assert "nothing is checked" in result.detail

    def test_re_measuring_writes_the_ceiling_the_tree_actually_has(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        measured = {"raven/core/x.py": ["raven/core/x.py:1 f()", "raven/core/x.py:2 g()"], "raven/core/y.py": ["y"]}
        monkeypatch.setattr(ca, "_untyped_definitions", lambda: measured)
        path = tmp_path / "untyped_baseline.json"
        monkeypatch.setattr(ca, "ANNOTATION_BASELINE", path)
        result = ca.check_annotations(write_baseline=True)
        assert result.status == "pass"
        assert json.loads(path.read_text(encoding="utf-8")) == {"raven/core/x.py": 2, "raven/core/y.py": 1}
        assert ca.check_annotations().status == "pass"

    def test_the_shipped_ceiling_is_the_shipped_tree(self) -> None:
        """The debt is recorded as measured, not as remembered: this fails the moment a function is
        added without hints, or one is fixed and the ceiling is left to rot."""
        result = ca.check_annotations()
        assert result.status == "pass", result.detail
        ceiling = json.loads(ca.ANNOTATION_BASELINE.read_text(encoding="utf-8"))
        assert result.counts["functions"] == sum(ceiling.values())


class TestBanditStage:
    """The security-lint stage reads a report, so every shape of a report that cannot certify the tree
    clean has to fail it — including a tree where bandit never ran to produce one."""

    @staticmethod
    def _report(results: list[dict[str, Any]], errors: list[Any] | None = None) -> str:
        totals = {"SEVERITY.LOW": sum(1 for r in results if r["issue_severity"] == "LOW")}
        return json.dumps({"errors": errors or [], "results": results, "metrics": {"_totals": totals}})

    @staticmethod
    def _finding(test_id: str = "B324", severity: str = "HIGH", line: int = 5) -> dict[str, Any]:
        return {
            "filename": "raven\\core\\rag\\embeddings.py",
            "line_number": line,
            "test_id": test_id,
            "issue_severity": severity,
            "issue_text": "Use of weak MD5 hash for security.",
        }

    def _stub(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stdout: str,
        stderr: str = "",
        unannotated_stdout: str | None = None,
        annotations: Counter[tuple[str, str]] | None = None,
    ) -> list[list[str]]:
        calls: list[list[str]] = []

        def _inner(cmd: list[str], timeout: int = 0, env: dict[str, str] | None = None, cwd: Any = None) -> Any:
            calls.append(cmd)
            out = unannotated_stdout if "--ignore-nosec" in cmd and unannotated_stdout is not None else stdout
            return subprocess.CompletedProcess(cmd, 1, stdout=out, stderr=stderr)

        monkeypatch.setattr(ca, "_run", _inner)
        monkeypatch.setattr(ca, "_nosec_annotations", lambda targets: Counter() if annotations is None else annotations)
        return calls

    def test_a_high_finding_fails_the_stage_by_file_line_and_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, self._report([self._finding()]))
        result = ca.check_bandit()
        assert result.status == "fail"
        assert result.counts["high"] == 1
        assert "embeddings.py:5 B324" in result.detail

    def test_a_medium_finding_fails_the_stage_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, self._report([self._finding("B307", "MEDIUM", 2)]))
        result = ca.check_bandit()
        assert result.status == "fail"
        assert result.counts["medium"] == 1

    def test_a_tree_of_only_low_findings_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        low = [self._finding("B404", "LOW", 1), self._finding("B603", "LOW", 4)]
        self._stub(monkeypatch, self._report(low))
        result = ca.check_bandit()
        assert result.status == "pass"
        assert result.detail == "2 low-severity notes"

    def test_the_shipped_code_is_scanned_and_the_test_code_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._stub(monkeypatch, self._report([]))
        ca.check_bandit()
        assert calls[0][:4] == [sys.executable, "-m", "bandit", "--quiet"]
        assert set(ca.BANDIT_DIRS) <= set(calls[0]), calls[0]
        assert "tests/" not in calls[0] and "tests" not in calls[0]

    def test_no_report_is_a_failure_and_not_a_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, "", stderr="No module named bandit")
        result = ca.check_bandit()
        assert result.status == "fail"
        assert "No module named bandit" in result.detail

    def test_bandit_cannot_parsing_the_tree_is_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, self._report([], errors=[{"filename": "raven/x.py", "reason": "syntax error"}]))
        result = ca.check_bandit()
        assert result.status == "fail"
        assert "could not parse" in result.detail

    def test_a_nosec_id_bandit_does_not_recognise_fails_the_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Written as `# nosec B608 - the reason`, the reason is read as a list of test ids, so the
        annotation suppresses nothing and the line it covers is never checked."""
        warn = "[manager]\tWARNING\tTest in comment: reason is not a test name or id, ignoring"
        self._stub(monkeypatch, self._report([]), stderr=warn)
        result = ca.check_bandit()
        assert result.status == "fail"
        assert "does not know" in result.detail
        assert "reason" in result.detail

    def test_an_annotation_that_suppresses_nothing_fails_the_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tree was fixed under the comment and the comment stayed: a control that controls nothing."""
        key = str(ca.ROOT / "raven" / "core" / "sandbox.py")
        self._stub(
            monkeypatch,
            self._report([]),
            unannotated_stdout=self._report([]),
            annotations=Counter({(key, "B102"): 1}),
        )
        result = ca.check_bandit()
        assert result.status == "fail"
        assert "suppress nothing" in result.detail
        assert "B102" in result.detail

    def test_an_annotation_that_erases_a_real_finding_is_counted_and_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = str(ca.ROOT / "raven" / "core" / "sandbox.py")
        annotated = self._report([])
        unannotated = self._report(
            [
                {
                    "filename": key,
                    "line_number": 191,
                    "test_id": "B102",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Use of exec detected.",
                }
            ]
        )
        self._stub(
            monkeypatch,
            annotated,
            unannotated_stdout=unannotated,
            annotations=Counter({(key, "B102"): 1}),
        )
        result = ca.check_bandit()
        assert result.status == "pass"
        assert result.counts["nosec"] == 1


class TestGeneratedWriters:
    """`Path.write_text` on Windows turns every `\\n` into `\\r\\n`, and `.gitattributes` (`* text eol=lf`)
    hides the result: the working copy of a generated file goes CRLF while `git status` stays clean.
    Six writers in four scripts did exactly that until the tree was measured; this stage is what keeps
    the shape, so it has to fail on the exact call that produced the bug and not on the fix."""

    @staticmethod
    def _script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "gen.py").write_text(body, encoding="utf-8")
        monkeypatch.setattr(ca, "ROOT", tmp_path)

    def test_a_text_mode_writer_fails_and_names_the_file_and_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script(
            tmp_path, monkeypatch, "from pathlib import Path\nPath('out.js').write_text('a', encoding='utf-8')\n"
        )
        result = ca.check_generated_writers()
        assert result.status == "fail"
        assert "scripts/gen.py:2" in result.detail
        assert result.counts == {"writers": 1, "offenders": 1}

    def test_writing_bytes_is_accepted_without_a_newline_argument(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script(tmp_path, monkeypatch, "from pathlib import Path\nPath('out.js').write_bytes(b'a')\n")
        result = ca.check_generated_writers()
        assert result.status == "pass", result.detail
        assert result.counts == {"writers": 1, "offenders": 0}

    def test_an_explicit_lf_newline_is_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._script(
            tmp_path,
            monkeypatch,
            "from pathlib import Path\nPath('o.css').write_text('a', encoding='utf-8', newline='\\n')\n",
        )
        assert ca.check_generated_writers().status == "pass"

    def test_a_newline_argument_that_is_not_lf_is_still_a_crlf_writer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script(
            tmp_path,
            monkeypatch,
            "from pathlib import Path\nPath('o.css').write_text('a', newline='\\r\\n')\n",
        )
        assert ca.check_generated_writers().status == "fail"

    def test_a_writer_inside_a_function_is_counted_where_it_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script(
            tmp_path,
            monkeypatch,
            "from pathlib import Path\n\n\ndef main() -> int:\n    Path('o.js').write_text('a')\n    return 0\n",
        )
        result = ca.check_generated_writers()
        assert result.status == "fail"
        assert "scripts/gen.py:5" in result.detail

    def test_a_script_that_cannot_be_parsed_fails_rather_than_passing_unread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script(tmp_path, monkeypatch, "def broken(\n")
        result = ca.check_generated_writers()
        assert result.status == "fail"
        assert "cannot parse" in result.detail

    def test_the_shipped_scripts_write_every_committed_file_in_lf(self) -> None:
        """Against the real tree: five writer calls, six before `record_site_frames.py` folded its
        three generated files through one helper."""
        result = ca.check_generated_writers()
        assert result.status == "pass", result.detail
        assert result.counts["writers"] >= 5
