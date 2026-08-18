from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.runtime.sandbox as sandbox_mod
from ravencode.runtime.sandbox import Sandbox, get_sandbox, sandbox_exec


@pytest.fixture(autouse=True)
def reset() -> Generator[None, None, None]:
    sandbox_mod._sandbox = None
    yield
    sandbox_mod._sandbox = None


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TestSandbox:
    async def test_run_code_python(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"ok")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        result = await Sandbox().run_code("print(1)")
        assert result == "ok"
        assert calls[0][0] == "docker"
        assert "python:3.11-slim" in calls[0]
        assert "python" in calls[0] and "/workspace/script.py" in calls[0]

    async def test_run_code_custom_language(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"ok")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        result = await Sandbox().run_code("echo hi", language="bash")
        assert result == "ok"
        assert "/workspace/code.sh" in calls[0]

    async def test_run_code_unknown_language_defaults_python(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        result = await Sandbox().run_code("x", language="cobol")
        assert result == "(no output)"
        assert "/workspace/code.txt" in calls[0]

    async def test_run_command_splits(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        await Sandbox().run_command('echo "hello world"')
        assert calls[0][-2:] == ["echo", "hello world"]

    async def test_docker_exec_with_volumes(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"out")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        result = await Sandbox().run_code("code", language="python")
        assert result == "out"
        vols = next(c for c in calls[0] if c.startswith("-v"))
        assert vols == "-v" and calls[0][calls[0].index("-v") + 1].endswith(":ro")

    async def test_docker_exec_no_volumes(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            return _proc(b"out")

        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", fake_exec)
        await Sandbox().run_command("ls")
        assert "-v" not in calls[0]

    async def test_docker_exec_timeout(self, monkeypatch) -> None:
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError())
        monkeypatch.setattr("ravencode.runtime.sandbox.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        result = await Sandbox(timeout=30).run_code("x")
        assert result == "[sandbox timeout after 30s]"

    async def test_stderr_and_exit_code(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=_proc(b"out", b"boom", returncode=2)),
        )
        result = await Sandbox().run_code("x")
        assert result == "out\n[stderr]\nboom\n[exit code: 2]"

    async def test_output_truncated(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=_proc(b"x" * 40_000, b"y" * 20_000)),
        )
        result = await Sandbox().run_code("x")
        assert len(result) >= 30_000
        assert "[stderr]" in result


class TestGlobals:
    def test_get_sandbox_singleton(self) -> None:
        assert get_sandbox() is get_sandbox()

    def test_get_sandbox_reinit(self) -> None:
        first = get_sandbox()
        sandbox_mod._sandbox = None
        second = get_sandbox(image="img")
        assert second is not first
        assert second.image == "img"

    async def test_sandbox_exec_delegates(self, monkeypatch) -> None:
        fake = Sandbox()
        fake.run_code = AsyncMock(return_value="ran")  # type: ignore[method-assign]
        monkeypatch.setattr(sandbox_mod, "get_sandbox", lambda: fake)
        assert await sandbox_exec("code", "python") == "ran"
        fake.run_code.assert_awaited_once_with("code", "python")
