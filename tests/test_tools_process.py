from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import process as process_mod


class _FakeProc:
    def __init__(
        self,
        stdout: bytes | None = b"",
        stderr: bytes | None = b"",
        returncode: int | None = 0,
        *,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes | None, bytes | None]:
        if self._hang:
            await asyncio.Event().wait()
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int | None:
        self.waited = True
        return self.returncode


def _exec(proc: _FakeProc):
    return patch.object(process_mod.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))


class TestRunSubprocess:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        proc = _FakeProc(stdout=b"hello", stderr=b"warn", returncode=3)
        with _exec(proc):
            rc, out, err = await process_mod._run_subprocess(["echo", "hi"])
        assert rc == 3
        assert out == "hello"
        assert err == "warn"

    @pytest.mark.asyncio
    async def test_handles_none_returncode_and_stderr(self) -> None:
        proc = _FakeProc(stdout=b"ok", stderr=None, returncode=None)
        with _exec(proc):
            rc, out, err = await process_mod._run_subprocess(["cmd"])
        assert rc == 0
        assert out == "ok"
        assert err == ""

    @pytest.mark.asyncio
    async def test_timeout_kills_and_reraises(self) -> None:
        proc = _FakeProc(hang=True)
        with _exec(proc), pytest.raises(TimeoutError):
            await process_mod._run_subprocess(["slow"], timeout=0.01)
        assert proc.killed is True
        assert proc.waited is True


class TestProcessList:
    @pytest.mark.asyncio
    async def test_nt_strips_quotes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_mod.os, "name", "nt")
        proc = _FakeProc(stdout=b'"chrome.exe","123"\n"svchost.exe","456"')
        with _exec(proc):
            result = await process_mod.process_list()
        assert result == 'chrome.exe","123\nsvchost.exe","456'

    @pytest.mark.asyncio
    async def test_posix_truncates_to_50_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_mod.os, "name", "posix")
        body = "\n".join(f"line{i}" for i in range(80))
        proc = _FakeProc(stdout=body.encode())
        with _exec(proc):
            result = await process_mod.process_list()
        assert len(result.splitlines()) == 50
        assert result.splitlines()[0] == "line0"


class TestProcessKill:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(return_value=(0, "", ""))):
            assert await process_mod.process_kill(42) == "Process 42 terminated"

    @pytest.mark.asyncio
    async def test_nonzero_with_stderr(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(return_value=(1, "", "  denied  "))):
            assert await process_mod.process_kill(7) == "Failed to kill process 7: denied"

    @pytest.mark.asyncio
    async def test_nonzero_without_stderr_uses_unknown(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(return_value=(1, "", ""))):
            assert "unknown error" in await process_mod.process_kill(7)

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(side_effect=TimeoutError)):
            assert await process_mod.process_kill(9) == "Timeout killing process 9"

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(side_effect=FileNotFoundError)):
            assert await process_mod.process_kill(9) == "Kill command not found for process 9"

    @pytest.mark.asyncio
    async def test_permission_error(self) -> None:
        with patch.object(process_mod, "_run_subprocess", AsyncMock(side_effect=PermissionError)):
            assert await process_mod.process_kill(9) == "Permission denied to kill process 9"


class TestRegistration:
    def test_registers_both_tools(self) -> None:
        registry = ToolRegistry()
        process_mod.register_process_tools(registry)
        assert registry.get("process_list") is not None
        assert registry.get("process_kill") is not None
