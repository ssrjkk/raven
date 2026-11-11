from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from raven.core._pyrunner import run as pyrunner_run
from raven.core.sandbox import SandboxConfig, _validate_ast
from raven.core.security.code_sandbox import (
    DENIED_BUILTINS,
    DENIED_MODULES,
    PYTHON_RUNNER_MODULE,
    UNTRUSTED_CHILD_ENV_KEYS,
    python_code_issues,
    untrusted_child_env,
    validate_python_code,
)

ROOT = Path(__file__).resolve().parents[2]


class TestValidatePythonCode:
    def test_safe_code_passes(self) -> None:
        assert validate_python_code("1 + 1") is None
        assert validate_python_code("name = 'world'; out = f'hello {name}'") is None

    def test_dangerous_builtins_blocked(self) -> None:
        assert validate_python_code("eval('1+1')") is not None
        assert validate_python_code("open('x')") is not None
        assert validate_python_code("format(())") is not None
        assert validate_python_code("'{0.__class__.__mro__}'.format(())") is not None

    def test_dunder_escape_blocked(self) -> None:
        assert validate_python_code("f'{().__class__}'") is not None
        assert validate_python_code("().__class__.__bases__[0].__subclasses__()") is not None
        assert validate_python_code("print('__globals__')") is not None

    def test_from_import_cannot_import_denied_module(self) -> None:
        assert validate_python_code("from os import system; system('id')") is not None
        assert validate_python_code("from pathlib import Path; Path('.')") is not None

    def test_denied_modules_cover_io_surfaces(self) -> None:
        for mod in ("pathlib", "io", "urllib", "asyncio", "http", "multiprocessing", "threading", "sqlite3"):
            assert mod in DENIED_MODULES, f"{mod} must be denied"
            assert validate_python_code(f"import {mod}") is not None
            assert validate_python_code(f"from {mod} import something") is not None

    def test_attribute_call_on_denied_module(self) -> None:
        assert "os" in DENIED_MODULES
        assert validate_python_code("os.system('ls')") is not None
        assert validate_python_code("urllib.request.urlopen('http://x')") is not None

    def test_denied_builtins_set_is_shared(self) -> None:
        assert "open" in DENIED_BUILTINS
        assert "getattr" in DENIED_BUILTINS

    def test_syntax_error_returns_message(self) -> None:
        assert "Syntax" in (validate_python_code("def broken(") or "")

    def test_bare_dunder_name_reference_blocked(self) -> None:
        assert "__import__" in (validate_python_code("x = __import__") or "")
        assert "__builtins__" in (validate_python_code("print(__builtins__)") or "")


class TestPyrunner:
    def test_safe_code_executes(self) -> None:
        assert "2" in pyrunner_run("1 + 1")
        assert "hello" in pyrunner_run("'he' + 'llo'")

    def test_import_escape_blocked(self) -> None:
        for code in (
            "import os; os.system('echo pwned')",
            "from os import system; system('echo pwned')",
            "import pathlib; pathlib.Path('.')",
            "from urllib import request; request.urlopen('http://127.0.0.1')",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1')",
            "import asyncio; asyncio.run(asyncio.sleep(0))",
            "import io; io.open('/tmp/x')",
            "import threading; threading.Thread()",
            "import multiprocessing; multiprocessing.Process()",
            "import sqlite3; sqlite3.connect(':memory:')",
        ):
            assert "[denied]" in pyrunner_run(code), code

    def test_dunder_escape_blocked(self) -> None:
        assert "[denied]" in pyrunner_run("().__class__.__mro__")
        assert "[denied]" in pyrunner_run("print('__globals__')")

    def test_dangerous_builtin_blocked(self) -> None:
        assert "[denied]" in pyrunner_run("eval('1+1')")


class TestSandboxAst:
    def test_sandbox_now_blocks_io_modules(self) -> None:
        assert _validate_ast("import pathlib") is not None
        assert _validate_ast("import io") is not None
        assert _validate_ast("import urllib") is not None
        assert _validate_ast("import asyncio") is not None
        assert _validate_ast("from os import system") is not None
        assert _validate_ast("os.system('id')") is not None

    def test_sandbox_still_allows_safe_code(self) -> None:
        assert _validate_ast("print(1 + 1)") is None

    @pytest.mark.asyncio
    async def test_sandbox_direct_exec_blocks_escape(self) -> None:
        sandbox = _make_direct_sandbox()
        out = await sandbox.exec("import pathlib; pathlib.Path('.')")
        assert "[denied]" in out


def _make_direct_sandbox():
    from raven.core.sandbox import Sandbox

    return Sandbox(SandboxConfig(mode="none"))


def _function_source(rel_path: str, name: str) -> str:
    """The body of one function, read off disk so this gate costs no package imports."""
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{rel_path} has no function named {name}")


class TestUntrustedChildEnv:
    @pytest.mark.parametrize("spelling", ["SYSTEMROOT", "systemroot", "SystemRoot"])
    def test_windows_names_survive_whatever_casing_the_parent_carries(self, spelling: str) -> None:
        # The safelist once spelled this "SystemRoot" and tested membership case-sensitively against a
        # parent that spells it "SYSTEMROOT", so it was dropped; Winsock resolves its providers out of
        # %SYSTEMROOT%\System32 and every sandboxed child died with WinError 10106 before running a line.
        env = untrusted_child_env({spelling: "C:\\Windows", "Path": "C:\\Windows\\System32"})
        assert set(env) == {spelling, "Path"}
        assert env[spelling] == "C:\\Windows"

    def test_credentials_stay_with_the_gateway(self) -> None:
        parent = {
            "OPENAI_API_KEY": "sk-leak",
            "GH_TOKEN": "gho_leak",
            "WEB_SECRET_KEY": "hunter2",
            "AWS_SECRET_ACCESS_KEY": "wJalr",
            "TELEGRAM_BOT_TOKEN": "123456:ABC-D",
            "PATH": "C:\\Windows\\System32",
        }
        assert untrusted_child_env(parent) == {"PATH": "C:\\Windows\\System32"}

    def test_the_real_environment_yields_only_safelisted_names(self) -> None:
        env = untrusted_child_env()
        assert {key.upper() for key in env} <= UNTRUSTED_CHILD_ENV_KEYS
        if sys.platform == "win32":
            assert "SYSTEMROOT" in {key.upper() for key in env}


class TestRunnerModuleContract:
    def test_the_runner_lives_outside_the_tool_registry(self) -> None:
        # `raven.tools.__init__` builds every tool, which measured 13.1 s per sandboxed run against
        # 0.10 s for a bare interpreter, so the module the `-m` argument names must stay elsewhere.
        assert not PYTHON_RUNNER_MODULE.startswith("raven.tools")
        assert not (ROOT / "raven" / "tools" / "_pyrunner.py").exists()

    def test_importing_the_runner_does_not_import_the_tool_registry(self) -> None:
        probe = "import importlib, sys; importlib.import_module(sys.argv[1]); print('raven.tools' in sys.modules)"
        proc = subprocess.run(
            [sys.executable, "-c", probe, PYTHON_RUNNER_MODULE],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        assert proc.stdout.strip() == "False", proc.stderr[-400:]

    def test_the_runner_is_importable_and_answers_to_run(self) -> None:
        assert callable(importlib.import_module(PYTHON_RUNNER_MODULE).run)

    def test_the_bundle_names_the_runner(self) -> None:
        # PyInstaller follows the import graph; a module reached only through a `-m` string argument is
        # invisible to it, so the spec must name it or the EXE refuses to execute any code at all.
        spec = (ROOT / "scripts" / "raven.spec").read_text(encoding="utf-8")
        assert f'"{PYTHON_RUNNER_MODULE}"' in spec


class TestSpawnSitesShareTheContract:
    @pytest.mark.parametrize(
        ("rel_path", "func"),
        [
            ("raven/plugins/code/plugin.py", "run_python"),
            ("raven/plugins/process/plugin.py", "run_python"),
            ("raven/tools/shell.py", "python_code"),
        ],
    )
    def test_every_python_spawning_surface_sanitizes_and_uses_the_shared_runner(self, rel_path: str, func: str) -> None:
        source = _function_source(rel_path, func)
        assert "untrusted_child_env()" in source, f"{rel_path}:{func} would hand the child the gateway env"
        assert "PYTHON_RUNNER_MODULE" in source, f"{rel_path}:{func} hardcodes its own runner target"
        assert "os.environ" not in source


class TestIssueReporterIsTheGate:
    """A scanner that keeps its own list of refusals is a second opinion, and it can disagree."""

    @pytest.mark.parametrize(
        "src",
        [
            "1 + 1",
            "def f(x):\n    return x * 2",
            "eval('1+1')",
            "open('/etc/passwd')",
            "import os",
            "from os import system",
            "os.system('id')",
            "().__class__.__bases__",
            "print('__globals__')",
            "def broken(",
        ],
    )
    def test_the_first_reported_issue_is_exactly_what_the_gate_refuses(self, src: str) -> None:
        issues = python_code_issues(src)
        first = issues[0].message if issues else None
        assert first == validate_python_code(src)
        assert (first is None) == (not issues)

    def test_several_refusals_are_all_reported_with_their_line(self) -> None:
        issues = python_code_issues("import os\neval('1')\nopen('x')\n")
        assert [issue.line for issue in issues] == [1, 2, 3]
        assert "os" in issues[0].message

    def test_safe_code_earns_no_refusal(self) -> None:
        assert python_code_issues("def f(x):\n    return x + 1") == []

    def test_the_agreement_holds_over_real_sources(self) -> None:
        for path in sorted((ROOT / "raven" / "core").rglob("*.py"))[:60]:
            src = path.read_text(encoding="utf-8", errors="replace")
            issues = python_code_issues(src)
            assert (issues[0].message if issues else None) == validate_python_code(src), path
