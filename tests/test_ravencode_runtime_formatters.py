from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ravencode.runtime.formatters import format_file, format_files


@pytest.fixture(autouse=True)
def _set_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from ravencode.runtime import workspace as _ws

    token = _ws._workspace_var.set(str(tmp_path))
    yield
    _ws._workspace_var.reset(token)


class TestRunFormatter:
    async def test_timeout(self, monkeypatch) -> None:
        async def fake_wait(coro, timeout):
            raise TimeoutError()

        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.wait_for", fake_wait)
        result = await format_file("a.py")
        assert result == "[timeout] formatter for a.py"

    async def test_not_found(self, monkeypatch) -> None:
        async def fake_exec(*args, **kwargs):
            raise FileNotFoundError()

        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", fake_exec)
        result = await format_file("a.py")
        assert result == "[skipped] formatter not found for a.py"

    async def test_output_success(self, monkeypatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"fixed", b"")
        proc.returncode = 0
        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        result = await format_file("a.py")
        assert result == "fixed"

    async def test_output_with_stderr(self, monkeypatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"out", b"err text")
        proc.returncode = 1
        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        result = await format_file("a.py")
        assert result == "[format issues] out\nerr text"

    async def test_output_truncated(self, monkeypatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"x" * 3000, b"")
        proc.returncode = 1
        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        result = await format_file("a.py")
        assert len(result) == len("[format issues] ") + 2000


class TestFormatFile:
    async def test_unknown_extension(self) -> None:
        assert await format_file("a.unknown") == ""

    async def test_known_extension_uses_cmd(self, monkeypatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        exec_mock = AsyncMock(return_value=proc)
        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", exec_mock)
        assert await format_file("x.py") == ""
        assert exec_mock.await_args is not None
        assert exec_mock.await_args.args[0] == "ruff"

    async def test_case_insensitive(self, monkeypatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        monkeypatch.setattr("ravencode.runtime.formatters.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        assert await format_file("x.PY") == ""


class TestFormatFiles:
    async def test_multiple(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.formatters.format_file", AsyncMock(return_value="ran"))
        result = await format_files(["a.py", "b.py"])
        assert result == "ran\nran"

    async def test_empty_results(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.formatters.format_file", AsyncMock(return_value=""))
        assert await format_files(["a.unknown", "b.unknown"]) == "(no formatters applied)"

    async def test_mixed(self, monkeypatch) -> None:
        async def fake_format(p: str) -> str:
            return "ran" if p == "a.py" else ""

        monkeypatch.setattr("ravencode.runtime.formatters.format_file", fake_format)
        assert await format_files(["a.py", "b.unknown"]) == "ran"
