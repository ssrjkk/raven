"""The `code` plugin surface: what each of its five tools reports.

Written after the sandbox startup fix, when `run_python` was able to execute code on Windows at all.
`find_issues` is pinned to the gate's own verdicts rather than a hand-written list, because that list
was a second opinion that could silently disagree with the thing it claimed to predict; the rest
measure the reported counts, caps and error paths against the real implementations.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.security.code_sandbox import PYTHON_RUNNER_MODULE, UNTRUSTED_CHILD_ENV_KEYS
from raven.plugins.code.plugin import (
    PLUGIN_DESCRIPTION,
    PLUGIN_NAME,
    explain_code,
    find_issues,
    review_code,
    run_python,
    suggest_edit,
)


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> Any:
    proc = SimpleNamespace(returncode=returncode, kill=AsyncMock())
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _overview_names(out: str, label: str) -> tuple[str, ...]:
    """The names on a `**Classes:**` or `**Functions:**` line of a high-level explanation.

    Read from that line alone: the explanation echoes the source underneath, so a whole-output
    substring check would pass even when the list itself named too many or too few.
    """
    line = next((line for line in out.splitlines() if line.startswith(f"**{label}:**")), "")
    return tuple(name.strip() for name in line[len(f"**{label}:**") :].split(",")) if line else ()


class TestRunPython:
    async def test_last_expression_comes_back(self) -> None:
        assert (await run_python("21 * 2")).strip() == "42"

    async def test_statement_without_a_value_reports_that_it_ran(self) -> None:
        assert "(code executed, no return value)" in await run_python("x = 1")

    async def test_stdout_is_kept(self) -> None:
        assert "hello" in await run_python('print("hello")')

    async def test_output_precedes_the_value_it_produced(self) -> None:
        out = await run_python('print("first")\n"second"')
        assert out.index("first") < out.index("second")

    async def test_the_ast_gate_denies_before_anything_runs(self) -> None:
        out = await run_python("__import__('os')")
        assert out.startswith("[denied]")
        assert "__import__" in out

    async def test_a_denied_module_import_is_refused(self) -> None:
        assert "[denied]" in await run_python("import socket")

    async def test_syntax_error_is_reported_not_raised(self) -> None:
        assert "Syntax Error:" in await run_python("def (")

    async def test_a_crash_reports_stderr_and_the_exit_code(self) -> None:
        out = await run_python("1 / 0")
        assert "[stderr]" in out
        assert "ZeroDivisionError" in out
        assert "[exit code: 1]" in out

    async def test_a_clean_run_carries_no_stderr_section(self) -> None:
        # The child used to boot the gateway's own settings, so every result ended with
        # `[stderr] ... Loaded WEB_SECRET_KEY from <path>`.
        assert "[stderr]" not in await run_python("1 + 1")

    async def test_output_is_capped_at_3000_chars(self) -> None:
        out = await run_python('print("x" * 4000)')
        assert len(out) == 3000

    async def test_timeout_kills_the_interpreter_and_says_so(self) -> None:
        assert await run_python("while True:\n    pass", timeout=1) == "Execution timed out after 1s"

    async def test_the_child_env_carries_only_safelisted_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAVEN_TEST_SECRET", "do-not-leak")
        monkeypatch.setenv("PATH", "/usr/bin")
        captured: dict[str, Any] = {}

        async def fake_exec(*args: Any, **kwargs: Any) -> Any:
            captured["args"] = args
            captured["env"] = kwargs["env"]
            return _proc(b"ok\n")

        with patch("raven.plugins.code.plugin.asyncio.create_subprocess_exec", fake_exec):
            await run_python("1")
        env = captured["env"]
        assert "RAVEN_TEST_SECRET" not in env
        assert "do-not-leak" not in env.values()
        assert env["PATH"] == "/usr/bin"
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert {key.upper() for key in env} <= (
            UNTRUSTED_CHILD_ENV_KEYS | {"PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE"}
        )
        assert captured["args"][1:3] == ("-m", PYTHON_RUNNER_MODULE)


class TestRunPythonFailureReporting:
    async def test_empty_output_is_not_an_empty_string(self) -> None:
        with patch("raven.plugins.code.plugin.asyncio.create_subprocess_exec", AsyncMock(return_value=_proc())):
            assert await run_python("1") == "(no output)"

    async def test_a_spawn_failure_is_reported_as_an_error(self) -> None:
        with patch(
            "raven.plugins.code.plugin.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("no interpreter")),
        ):
            assert await run_python("1") == "Error: no interpreter"

    async def test_stderr_without_a_traceback_is_still_appended(self) -> None:
        proc = _proc(b"out\n", b"warning: thing\n", 0)
        with patch("raven.plugins.code.plugin.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            assert await run_python("1") == "out\n\n[stderr]\nwarning: thing\n"

    async def test_blank_stderr_is_not_appended(self) -> None:
        proc = _proc(b"out\n", b"   \n", 0)
        with patch("raven.plugins.code.plugin.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            assert await run_python("1") == "out\n"


class TestReviewCode:
    def test_clean_code_says_so(self) -> None:
        out = review_code("x = 1", language="python")
        assert "No obvious issues found" in out
        assert "## Code Review — python" in out

    def test_long_code_is_flagged(self) -> None:
        assert ">500 chars" in review_code("x = 1\n" * 120)

    def test_wildcard_import_is_flagged(self) -> None:
        assert "Wildcard imports" in review_code("from os import *")

    @pytest.mark.parametrize("src", ["exec('x')", "eval('x')"])
    def test_dynamic_execution_is_flagged(self, src: str) -> None:
        assert "eval/exec detected" in review_code(src)

    @pytest.mark.parametrize("marker", ["TODO", "FIXME", "HACK"])
    def test_markers_are_flagged(self, marker: str) -> None:
        assert "TODO/FIXME markers" in review_code(f"# {marker} later")

    def test_debug_print_inside_a_function_is_flagged(self) -> None:
        assert "Debug print()" in review_code("def f():\n    print(1)")

    def test_print_at_module_level_is_not_flagged(self) -> None:
        assert "Debug print()" not in review_code("print(1)")

    @pytest.mark.parametrize("word", ["password", "SECRET", "Token"])
    def test_possible_secrets_are_flagged_case_insensitively(self, word: str) -> None:
        assert "hardcoded secret" in review_code(f'{word} = "x"')

    def test_the_code_is_echoed_up_to_1500_chars(self) -> None:
        out = review_code("y" * 2000)
        assert "y" * 1500 in out
        assert "y" * 1501 not in out

    def test_every_rule_fires_at_once(self) -> None:
        src = "from os import *\n# TODO\ndef f():\n    print(1)\npassword = 'x'\neval('1')\n" + "z = 1\n" * 120
        out = review_code(src)
        for fragment in (
            ">500 chars",
            "Wildcard imports",
            "eval/exec detected",
            "TODO/FIXME",
            "Debug print()",
            "hardcoded secret",
        ):
            assert fragment in out


class TestSuggestEdit:
    def test_counts_are_measured_from_the_ast(self) -> None:
        src = "import os\nfrom pathlib import Path\n\nclass C:\n    def m(self):\n        return len([1])\n"
        out = suggest_edit(src, "anything")
        assert "1 function(s), 1 class(es), 2 import(s)" in out
        assert "1 call(s)" in out

    def test_no_calls_means_no_call_hint(self) -> None:
        assert "call(s)" not in suggest_edit("x = 1", "anything")

    @pytest.mark.parametrize(
        ("goal", "fragment"),
        [
            ("optimize", "cProfile"),
            ("perf", "comprehensions"),
            ("speed", "lru_cache"),
            ("read", "smaller ones"),
            ("readability", "type hints"),
            ("clean", "magic numbers"),
            ("test", "pytest"),
            ("tests", "Mock external"),
            ("unittest", "failure paths"),
            ("security", "eval()"),
            ("secure", "untrusted input"),
            ("safe", "parameterized queries"),
        ],
    )
    def test_each_goal_has_its_own_advice(self, goal: str, fragment: str) -> None:
        assert fragment in suggest_edit("x = 1", goal)

    def test_goal_matching_is_case_insensitive(self) -> None:
        assert "cProfile" in suggest_edit("x = 1", "OPTIMIZE")

    def test_an_unknown_goal_still_reports_the_analysis(self) -> None:
        out = suggest_edit("x = 1", "refactor")
        assert "**Goal:** refactor" in out
        assert "0 function(s)" in out

    def test_a_parse_error_is_reported_not_raised(self) -> None:
        assert "Parse error:" in suggest_edit("def (", "test")

    def test_the_code_is_echoed_up_to_1500_chars(self) -> None:
        out = suggest_edit("q" * 2000, "read")
        assert "q" * 1500 in out
        assert "q" * 1501 not in out


class TestExplainCode:
    def test_high_level_lists_classes_functions_and_constants(self) -> None:
        src = "MAX = 3\n\nclass Widget:\n    def spin(self):\n        pass\n\ndef build():\n    pass\n"
        out = explain_code(src)
        assert _overview_names(out, "Classes") == ("Widget",)
        assert set(_overview_names(out, "Functions")) == {"spin", "build"}
        assert "**Constant:** MAX" in out
        assert "top-level statement(s)" in out
        assert "(high level)" in out

    def test_line_and_char_counts_are_measured(self) -> None:
        assert "**2 lines, ~11 chars**" in explain_code("a = 1\nb = 2")

    def test_lowercase_assignments_are_not_constants(self) -> None:
        assert "**Constant:**" not in explain_code("lower = 1")

    def test_low_level_numbers_the_lines(self) -> None:
        out = explain_code("a = 1\n\nb = 2", detail="low")
        assert "(low level)" in out
        assert "` 1` | a = 1" in out
        assert "` 3` | b = 2" in out

    def test_low_level_caps_at_40_lines(self) -> None:
        out = explain_code("\n".join(f"x{i} = {i}" for i in range(60)), detail="low")
        assert "`40` |" in out
        assert "`41` |" not in out

    def test_low_level_skips_blank_lines(self) -> None:
        out = explain_code("\n\n\na = 1", detail="low")
        assert "` 4` | a = 1" in out
        assert out.count("|") == 1

    def test_empty_code_low_level_says_empty(self) -> None:
        assert "(empty)" in explain_code("", detail="low")

    def test_a_parse_error_is_reported_not_raised(self) -> None:
        assert "Parse error:" in explain_code("def (")

    def test_the_code_is_echoed_up_to_2000_chars(self) -> None:
        out = explain_code("w" * 2500)
        assert "w" * 2000 in out
        assert "w" * 2001 not in out

    def test_at_most_five_classes_and_eight_functions_are_named(self) -> None:
        src = "\n".join(f"class C{i}:\n    pass" for i in range(7))
        src += "\n" + "\n".join(f"def f{i}():\n    pass" for i in range(10))
        out = explain_code(src)
        assert _overview_names(out, "Classes") == tuple(f"C{i}" for i in range(5))
        assert _overview_names(out, "Functions") == tuple(f"f{i}" for i in range(8))


class TestFindIssues:
    """`find_issues` must predict what the sandbox gate will do, because that is the only reason it exists."""

    @pytest.mark.parametrize("src", ["eval('1+1')", "exec('x=1')", "compile('x', 'f', 'exec')", "input()"])
    def test_a_bare_denied_builtin_is_flagged(self, src: str) -> None:
        out = find_issues(src)
        assert "the runner refuses this code" in out
        assert "No AST-level issues found" not in out

    @pytest.mark.parametrize(
        "src", ["builtins.eval('1')", "builtins.exec('x')", "builtins.compile('x','f','exec')", "builtins.input()"]
    )
    def test_the_attribute_form_is_flagged_too(self, src: str) -> None:
        assert "refuses" in find_issues(src)

    def test_a_method_named_like_a_denied_builtin_is_flagged_because_the_runner_refuses_it(self) -> None:
        # The gate denies any `.input()` call, so a scanner that stayed quiet about it would promise
        # a run the sandbox then refuses.
        assert "refuses" in find_issues("form.input()")

    def test_the_line_number_is_the_call_site(self) -> None:
        assert "Line 3:" in find_issues("a = 1\nb = 2\neval('1')")

    @pytest.mark.parametrize("src", ["import os", "from socket import socket", "().__class__", "open('x')"])
    def test_the_other_refusals_the_gate_makes_are_reported(self, src: str) -> None:
        assert "refuses" in find_issues(src)

    def test_a_bare_except_is_flagged(self) -> None:
        assert "Bare except" in find_issues("try:\n    pass\nexcept:\n    pass")

    def test_a_typed_except_is_not_flagged(self) -> None:
        assert "Bare except" not in find_issues("try:\n    pass\nexcept ValueError:\n    pass")

    def test_two_handlers_are_not_flagged_as_bare(self) -> None:
        src = "try:\n    pass\nexcept ValueError:\n    pass\nexcept:\n    pass"
        assert "Bare except" not in find_issues(src)

    def test_clean_code_reports_clean(self) -> None:
        assert "No AST-level issues found" in find_issues("def f(x):\n    return x + 1")

    def test_a_parse_error_is_reported_not_raised(self) -> None:
        assert "Syntax Error:" in find_issues("def (")

    @pytest.mark.parametrize(
        "src",
        [
            "eval('1+1')",
            "exec('x=1')",
            "compile('x', 'f', 'exec')",
            "input()",
            "open('x')",
            "__import__('os')",
            "import os",
            "from pathlib import Path",
            "().__class__.__bases__[0].__subclasses__()",
            "print('__globals__')",
            "os.system('ls')",
            "'{0.__class__}'.format(()",
        ],
    )
    def test_nothing_the_gate_refuses_is_ever_reported_clean(self, src: str) -> None:
        from raven.core.security.code_sandbox import validate_python_code

        if validate_python_code(src) is None:
            pytest.fail(f"{src!r} is no longer refused by the gate; drop it from this corpus")
        assert "No AST-level issues found" not in find_issues(src)


class TestPluginMetadata:
    def test_the_plugin_names_itself(self) -> None:
        assert PLUGIN_NAME == "code"
        assert PLUGIN_DESCRIPTION

    def test_the_module_is_a_real_file_in_the_tree(self) -> None:
        import raven.plugins.code.plugin as mod

        assert Path(mod.__file__).is_file()


class TestNoEventLoopLeak:
    async def test_a_timed_out_run_does_not_block_the_next_one(self) -> None:
        assert await run_python("while True:\n    pass", timeout=1) == "Execution timed out after 1s"
        assert (await asyncio.wait_for(run_python("6 * 7"), timeout=30)).strip() == "42"
