from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools import shell as shell_mod
from raven.tools.db import db_query
from raven.tools.file import file_append, file_delete, file_list, file_read, file_write, register_file_tools
from raven.tools.register_all import create_tool_registry, register_all_tools
from raven.tools.shell import python_code, shell_command
from raven.tools.utils import get_timestamp, wait_for

# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

class TestFileTools:
    @pytest.fixture
    def tmp_workspace(self, tmp_path: Path) -> Generator[Path, None, None]:
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        yield tmp_path
        if old:
            os.environ["RAVEN_WORKSPACE"] = old
        else:
            os.environ.pop("RAVEN_WORKSPACE", None)

    async def test_file_read_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "hello.txt"
        f.write_text("Hello, World!", encoding="utf-8")
        result = await file_read(str(f))
        assert "Hello, World!" in result

    async def test_file_read_not_found(self, tmp_workspace: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await file_read(str(tmp_workspace / "nonexistent.txt"))

    async def test_file_read_outside_workspace(self, tmp_workspace: Path) -> None:
        outside = Path(tempfile.gettempdir()) / "outside_test.txt"
        outside.write_text("hack", encoding="utf-8")
        with pytest.raises(PermissionError):
            await file_read(str(outside))
        outside.unlink(missing_ok=True)

    async def test_file_write_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "new.txt"
        result = await file_write(str(f), "test content")
        assert "Written" in result
        assert f.read_text(encoding="utf-8") == "test content"

    async def test_file_write_outside_workspace(self, tmp_workspace: Path) -> None:
        outside = Path(tempfile.gettempdir()) / "write_test.txt"
        with pytest.raises(PermissionError):
            await file_write(str(outside), "data")

    async def test_file_append_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "append.txt"
        f.write_text("base", encoding="utf-8")
        await file_append(str(f), "+more")
        assert f.read_text(encoding="utf-8") == "base+more"

    async def test_file_list_ok(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "a.py").write_text("", encoding="utf-8")
        (tmp_workspace / "b.py").write_text("", encoding="utf-8")
        result = await file_list(str(tmp_workspace), "*.py")
        assert "a.py" in result
        assert "b.py" in result

    async def test_file_list_empty(self, tmp_workspace: Path) -> None:
        result = await file_list(str(tmp_workspace))
        assert "(empty)" in result

    async def test_file_delete_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "del.txt"
        f.write_text("x", encoding="utf-8")
        result = await file_delete(str(f))
        assert "Deleted" in result
        assert not f.exists()

    async def test_file_delete_not_found(self, tmp_workspace: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await file_delete(str(tmp_workspace / "ghost.txt"))


# ---------------------------------------------------------------------------
# Shell tools
# ---------------------------------------------------------------------------

class TestShellTools:
    async def test_shell_echo(self) -> None:
        result = await shell_command("echo hello")
        assert "hello" in result

    async def test_shell_denied(self) -> None:
        result = await shell_command("sudo rm -rf /")
        assert "denied" in result

    async def test_shell_timeout(self) -> None:
        import platform
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 10"
        result = await shell_command(cmd, timeout=1)
        assert "timeout" in result

    async def test_python_ok(self) -> None:
        result = await python_code("1 + 1")
        assert "2" in result

    async def test_python_denied_builtin(self) -> None:
        result = await python_code("eval('1+1')")
        assert "denied" in result

    async def test_python_denied_import(self) -> None:
        result = await python_code("import os; os.system('ls')")
        assert "denied" in result

    async def test_python_error_handled(self) -> None:
        result = await python_code("1/0")
        assert "Error" in result or "ZeroDivision" in result

    async def test_python_denied_format_bypass(self) -> None:
        result = await python_code("'{0.__class__.__mro__}'.format(())")
        assert "denied" in result

    async def test_python_denied_format_map_bypass(self) -> None:
        result = await python_code("'{}'.format_map({})")
        assert "denied" in result

    async def test_python_denied_builtin_format(self) -> None:
        result = await python_code("format(())")
        assert "denied" in result

    async def test_python_fstring_dunder_blocked(self) -> None:
        result = await python_code("f'{().__class__}'")
        assert "denied" in result

    async def test_python_legit_format_style_ok(self) -> None:
        result = await python_code("name = 'world'; out = f'hello {name}'")
        assert "executed" in result


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

class TestDBTools:
    @pytest.fixture
    def tmp_workspace(self, tmp_path: Path) -> Generator[Path, None, None]:
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        yield tmp_path
        if old:
            os.environ["RAVEN_WORKSPACE"] = old
        else:
            os.environ.pop("RAVEN_WORKSPACE", None)

    async def test_db_query_select(self, tmp_workspace: Path) -> None:
        import sqlite3
        db = tmp_workspace / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'hello')")
        conn.commit()
        conn.close()
        result = await db_query("SELECT * FROM t", db_path=str(db))
        assert "hello" in result

    async def test_db_query_not_select(self, tmp_workspace: Path) -> None:
        import sqlite3
        db = tmp_workspace / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (id INT)")
        conn.commit()
        conn.close()
        result = await db_query("DROP TABLE t", db_path=str(db))
        assert "Only SELECT" in result

    async def test_db_query_not_found(self) -> None:
        result = await db_query("SELECT 1", db_path="/nonexistent/db.sqlite")
        assert "not found" in result

    async def test_db_query_empty(self, tmp_workspace: Path) -> None:
        import sqlite3
        db = tmp_workspace / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (id INT)")
        conn.commit()
        conn.close()
        result = await db_query("SELECT * FROM t", db_path=str(db))
        assert "empty" in result


# ---------------------------------------------------------------------------
# Util tools
# ---------------------------------------------------------------------------

class TestUtilTools:
    async def test_wait(self) -> None:
        result = await wait_for(0.01)
        assert "Waited" in result

    async def test_timestamp(self) -> None:
        result = get_timestamp()
        assert "UTC" in result
        assert "20" in result


# ---------------------------------------------------------------------------
# ToolRegistry integration
# ---------------------------------------------------------------------------

class TestToolRegistryIntegration:
    def test_create_registry_has_all_tools(self) -> None:
        registry = create_tool_registry()
        assert registry.count >= 15  # at least 15 tools registered

    async def test_registry_call_file_read(self, tmp_path: Path) -> None:
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        registry = create_tool_registry()
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        result = await registry.call("file_read", path=str(f))
        assert "content" in result

    async def test_registry_call_timeout(self) -> None:
        async def hung() -> str:
            await asyncio.sleep(999)
            return "done"
        spec = ToolSpec(
            name="hung",
            description="hung tool",
            parameters={},
            handler=hung,
            timeout=1,
        )
        registry = ToolRegistry()
        registry.register(spec)
        result = await registry.call("hung")
        assert "timed out" in result

    async def test_registry_call_validate_fail(self) -> None:
        def validate(params: dict[str, Any]) -> str | None:
            if params.get("x") == "bad":
                return "x cannot be bad"
            return None

        async def handler(x: str) -> str:
            return "ok"

        spec = ToolSpec(
            name="validated",
            description="validated tool",
            parameters={"x": {"type": "string"}},
            handler=handler,
            validator_fn=validate,
        )
        registry = ToolRegistry()
        registry.register(spec)
        result = await registry.call("validated", x="bad")
        assert "x cannot be bad" in result

    async def test_registry_call_validate_pass(self) -> None:
        def validate(params: dict[str, Any]) -> str | None:
            return None

        async def handler(x: str) -> str:
            return "ok"

        spec = ToolSpec(
            name="validated",
            description="validated tool",
            parameters={"x": {"type": "string"}},
            handler=handler,
            validator_fn=validate,
        )
        registry = ToolRegistry()
        registry.register(spec)
        result = await registry.call("validated", x="good")
        assert result == "ok"

    async def test_registry_call_handler_error(self) -> None:
        async def broken() -> str:
            raise RuntimeError("oops")

        spec = ToolSpec(
            name="broken",
            description="broken tool",
            parameters={},
            handler=broken,
        )
        registry = ToolRegistry()
        registry.register(spec)
        result = await registry.call("broken")
        assert "oops" in result

    async def test_register_all_tools_no_duplicates(self) -> None:
        registry = ToolRegistry()
        register_all_tools(registry)
        count1 = registry.count
        register_all_tools(registry)
        assert registry.count == count1  # no dupes


# ---------------------------------------------------------------------------
# Test runner tools
# ---------------------------------------------------------------------------

class TestTestsTool:
    async def test_run_tests_denies_outside_workspace(self, tmp_path: Path) -> None:
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        try:
            outside = tempfile.gettempdir()
            from raven.tools.tests import run_tests

            result = await run_tests(path=outside)
            assert "Access denied" in result
        finally:
            if old is None:
                os.environ.pop("RAVEN_WORKSPACE", None)
            else:
                os.environ["RAVEN_WORKSPACE"] = old

    async def test_run_tests_missing_path(self, tmp_path: Path) -> None:
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        try:
            from raven.tools.tests import run_tests

            result = await run_tests(path=str(tmp_path / "missing"))
            assert "not found" in result
        finally:
            if old is None:
                os.environ.pop("RAVEN_WORKSPACE", None)
            else:
                os.environ["RAVEN_WORKSPACE"] = old

    async def test_sanitize_extra_args_drops_unsafe(self) -> None:
        from raven.tools.tests import _sanitize_extra_args

        kept, dropped = _sanitize_extra_args("--cov --tb=short --pdb --some-evil --rootdir=/etc")
        assert "--cov" in kept
        assert "--tb=short" in kept
        assert any("--pdb" in d for d in dropped)
        assert any("--some-evil" in d for d in dropped)
        assert any("--rootdir" in d for d in dropped)

    def test_pytest_summary_reads_banner_and_bare_counts(self) -> None:
        from raven.tools.tests import _pytest_summary

        assert _pytest_summary("======= 1 failed, 4 passed in 0.31s =======") == "1 failed, 4 passed in 0.31s"
        # narrow terminals and the coverage gate drop the "== ... ==" banner
        assert _pytest_summary("F.\n1 failed, 1 passed in 3.64s\n") == "1 failed, 1 passed in 3.64s"
        assert _pytest_summary("no counts in this output") == "unknown"

    async def test_run_tests_reports_counts_for_real_suite(self, tmp_path: Path) -> None:
        from raven.tools.tests import run_tests

        # the inifile stops pytest from climbing out of the scratch dir into an ambient config
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (tmp_path / "test_mini.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        try:
            result = await run_tests(path=str(tmp_path), timeout=60)
            assert "Tests: unknown" not in result
            assert "1 passed" in result
        finally:
            if old is None:
                os.environ.pop("RAVEN_WORKSPACE", None)
            else:
                os.environ["RAVEN_WORKSPACE"] = old

    async def test_coverage_reads_report_from_the_requested_path(self, tmp_path: Path, monkeypatch) -> None:
        from raven.tools import tests as tests_module

        report = tmp_path / "coverage.xml"
        report.write_text('<coverage line-rate="0.75"><packages/></coverage>', encoding="utf-8")

        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"7 passed in 1.0s\n", b""

        captured: list[list[str]] = []

        async def fake_exec(*args: str, **kwargs: Any) -> _Proc:
            captured.append(list(args))
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        old = os.environ.get("RAVEN_WORKSPACE")
        os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
        try:
            result = await tests_module.test_coverage(path=str(tmp_path), timeout=30)
        finally:
            if old is None:
                os.environ.pop("RAVEN_WORKSPACE", None)
            else:
                os.environ["RAVEN_WORKSPACE"] = old

        xml_arg = next(a for a in captured[0] if a.startswith("--cov-report=xml:"))
        assert Path(xml_arg.split("xml:", 1)[1]) == report.resolve()
        assert "Coverage: 75.0%" in result
        assert "7 passed" in result
        assert not report.exists()

    async def test_sanitize_extra_args_allows_safe(self) -> None:
        from raven.tools.tests import _sanitize_extra_args

        kept, dropped = _sanitize_extra_args("--maxfail=1 -x -k test_foo")
        assert "-x" in kept.split()
        assert "-k" in kept.split()
        assert any("test_foo" in d for d in dropped)


# ---------------------------------------------------------------------------
# Shell / python sandbox branches driven with mocked subprocess
# ---------------------------------------------------------------------------

class TestShellValidation:
    async def test_empty_command_denied(self) -> None:
        assert await shell_command("") == "[denied] empty command"

    async def test_find_exec_flag_denied(self) -> None:
        result = await shell_command("find . -exec rm {} ;")
        assert result == "[denied] find flag '-exec' is not allowed"

    async def test_find_without_forbidden_flag_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"./a.txt\n", b""

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await shell_command("find . -name a.txt")
        assert "./a.txt" in result

    @pytest.mark.parametrize("argument", ["a&b", "a|b", "a>b", "a<b", "a^b", "a\nb"])
    def test_cmd_metacharacters_rejected(self, argument: str) -> None:
        with pytest.raises(ValueError, match="cmd metacharacter"):
            shell_mod._reject_cmd_metacharacters(["echo", argument])

    async def test_windows_builtin_with_metacharacter_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shell_mod, "_IS_WINDOWS", True)
        result = await shell_command("echo benign & echo pwned")
        assert result == "[denied] cmd metacharacter in argument: '&'"

    async def test_windows_clean_builtin_runs_through_cmd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shell_mod, "_IS_WINDOWS", True)
        seen: list[str] = []

        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"hi\n", b""

        async def fake_exec(*a: object, **_k: object) -> _Proc:
            seen.extend(str(x) for x in a)
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await shell_command("echo hi")
        assert result.strip() == "hi"
        assert seen[:3] == ["cmd", "/c", "echo"]


class TestShellOutputBranches:
    async def test_captures_stderr_and_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Proc:
            returncode = 2

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"STDOUT-OUT\n", b"somthing failed\n"

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await shell_command("echo hi")
        assert "STDOUT-OUT" in result
        assert "[stderr]" in result
        assert "somthing failed" in result
        assert "exit code: 2" in result


class TestPythonCodeBranches:
    async def test_no_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shell_mod, "validate_python_code", lambda _code: None)

        class _Proc:
            async def communicate(self, _data: object = None) -> tuple[bytes, bytes]:
                return b"", b""

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert await python_code("x = 1") == "(no output)"

    async def test_timeout_kills_and_waits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shell_mod, "validate_python_code", lambda _code: None)

        class _Proc:
            def __init__(self) -> None:
                self.killed = False

            def communicate(self, _data: object = None) -> None:
                return None

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                return -9

        procs: list[_Proc] = []

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            proc = _Proc()
            procs.append(proc)
            return proc

        async def fake_wait_for(_awaitable: object, timeout: object = None) -> None:
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        assert await python_code("import time; time.sleep(100)", timeout=1) == "[timeout after 1s]"
        assert procs[0].killed is True

    async def test_timeout_kill_process_already_gone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shell_mod, "validate_python_code", lambda _code: None)

        class _Proc:
            def communicate(self, _data: object = None) -> None:
                return None

            def kill(self) -> None:
                raise ProcessLookupError

            async def wait(self) -> int:
                return 0

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        async def fake_wait_for(_awaitable: object, timeout: object = None) -> None:
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        assert await python_code("x", timeout=2) == "[timeout after 2s]"

    async def test_syntax_error_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_code: str) -> None:
            raise SyntaxError("invalid syntax")

        monkeypatch.setattr(shell_mod, "validate_python_code", _boom)
        assert await python_code("def f(:") == "Syntax Error: invalid syntax"

    async def test_unexpected_exception_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_code: str) -> None:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(shell_mod, "validate_python_code", _boom)
        assert await python_code("x") == "Error: kaboom"


# ---------------------------------------------------------------------------
# tests.py tool: marker/args, subprocess failure modes, generate_tests
# ---------------------------------------------------------------------------

class _OkProc:
    returncode = 0

    def __init__(self, out: bytes = b"5 passed in 0.10s\n", err: bytes = b"") -> None:
        self._out = out
        self._err = err

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._out, self._err


class TestRunTestsBranches:
    async def test_marker_and_safe_args_added(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import run_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_k: object) -> _OkProc:
            captured.append(list(args))
            return _OkProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await run_tests(path=str(tmp_path), marker="slow", extra_args="--tb=long -x")
        cmd = captured[0]
        assert "-m" in cmd and "slow" in cmd
        assert "--tb=long" in cmd and "-x" in cmd
        assert "5 passed" in result

    async def test_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import run_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))

        class _HangProc:
            returncode = None

            def communicate(self) -> None:
                return None

        async def fake_exec(*_a: str, **_k: object) -> _HangProc:
            return _HangProc()

        async def fake_wait_for(_aw: object, timeout: object = None) -> None:
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        assert await run_tests(path=str(tmp_path), timeout=3) == "Tests timed out after 3s"

    async def test_pytest_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import run_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))

        async def fake_exec(*_a: str, **_k: object) -> None:
            raise FileNotFoundError("no pytest")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert await run_tests(path=str(tmp_path)) == "pytest not found"


class TestCoverageBranches:
    async def test_access_denied_outside_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import test_coverage

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        result = await test_coverage(path=str(tmp_path.parent))
        assert result == "Access denied: invalid path"

    async def test_path_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import test_coverage

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        assert await test_coverage(path=str(tmp_path / "missing")) == "Path not found"

    async def test_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import test_coverage

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))

        class _HangProc:
            returncode = None

            def communicate(self) -> None:
                return None

        async def fake_exec(*_a: str, **_k: object) -> _HangProc:
            return _HangProc()

        async def fake_wait_for(_aw: object, timeout: object = None) -> None:
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        assert await test_coverage(path=str(tmp_path), timeout=2) == "Coverage run timed out after 2s"

    async def test_pytest_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import test_coverage

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))

        async def fake_exec(*_a: str, **_k: object) -> None:
            raise FileNotFoundError("boom")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await test_coverage(path=str(tmp_path))
        assert result.startswith("pytest not found:")

    async def test_malformed_coverage_xml_reports_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import test_coverage

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        (tmp_path / "coverage.xml").write_text("<<< not xml >>>", encoding="utf-8")

        async def fake_exec(*_a: str, **_k: object) -> _OkProc:
            return _OkProc(out=b"3 passed in 0.20s\n")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await test_coverage(path=str(tmp_path), timeout=30)
        assert "Coverage: 0.0%" in result
        assert "3 passed" in result


class TestGenerateTests:
    async def test_no_file_path(self) -> None:
        from raven.tools.tests import generate_tests

        assert await generate_tests("") == "file_path required"

    async def test_access_denied_outside_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import generate_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        result = await generate_tests(str(tmp_path.parent / "evil.py"))
        assert result == "Access denied: invalid path"

    async def test_file_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.tools.tests import generate_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        assert await generate_tests(str(tmp_path / "missing.py")) == "File not found"

    async def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        from raven.tools.tests import generate_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        src = tmp_path / "mod.py"
        src.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        class _Gen:
            async def generate_tests(self, _fp: str) -> str:
                return "def test_add():\n    assert add(1, 2) == 3\n"

            async def save_tests(self, _fp: str, _content: str) -> str:
                return "Saved 1 test"

        ns: Any = types.ModuleType("raven.coding.test_generator")
        ns.TestGenerator = _Gen
        monkeypatch.setitem(sys.modules, "raven.coding.test_generator", ns)
        result = await generate_tests(str(src))
        assert "Saved 1 test" in result
        assert "def test_add" in result

    async def test_empty_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        from raven.tools.tests import generate_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")

        class _Gen:
            async def generate_tests(self, _fp: str) -> str:
                return "   \n"

        ns: Any = types.ModuleType("raven.coding.test_generator")
        ns.TestGenerator = _Gen
        monkeypatch.setitem(sys.modules, "raven.coding.test_generator", ns)
        assert await generate_tests(str(src)) == "No tests generated (empty or unsupported)"

    async def test_generation_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        from raven.tools.tests import generate_tests

        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")

        class _Gen:
            async def generate_tests(self, _fp: str) -> str:
                raise RuntimeError("llm down")

        ns: Any = types.ModuleType("raven.coding.test_generator")
        ns.TestGenerator = _Gen
        monkeypatch.setitem(sys.modules, "raven.coding.test_generator", ns)
        assert await generate_tests(str(src)) == "Test generation failed"
