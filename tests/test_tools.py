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
            assert "outside workspace" in result
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

    async def test_sanitize_extra_args_allows_safe(self) -> None:
        from raven.tools.tests import _sanitize_extra_args

        kept, dropped = _sanitize_extra_args("--maxfail=1 -x -k test_foo")
        assert "-x" in kept.split()
        assert "-k" in kept.split()
        assert any("test_foo" in d for d in dropped)
