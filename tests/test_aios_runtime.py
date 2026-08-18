from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import aios.runtime.adapter as adapter_mod
from aios.runtime.adapter import RuntimeAdapter


class TestAiosRuntimeAdapter:
    @pytest.mark.asyncio
    async def test_run_command_echo(self):
        result = await RuntimeAdapter.run_command("echo hello")
        assert "hello" in result.rstrip()

    @pytest.mark.asyncio
    async def test_run_command_timeout(self):
        result = await RuntimeAdapter.run_command("echo timeout_test")
        assert isinstance(result, str)
        assert "timeout_test" in result

    @pytest.mark.asyncio
    async def test_unknown_command_rejected(self):
        result = await RuntimeAdapter.run_command("evil --rm -rf /")
        assert "not allowed" in result.lower()

    @pytest.mark.asyncio
    async def test_shell_operator_rejected_on_windows(self):
        result = await RuntimeAdapter.run_command("git status && echo PWNED")
        if sys.platform == "win32":
            assert "not allowed" in result.lower()
            assert "PWNED" not in result
        else:
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_shell_pipe_rejected_on_windows(self):
        result = await RuntimeAdapter.run_command("echo a | del C:\\Windows\\win.ini")
        if sys.platform == "win32":
            assert "not allowed" in result.lower()
        else:
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_redirect_rejected_on_windows(self):
        result = await RuntimeAdapter.run_command("echo x > C:\\temp\\evil.txt")
        if sys.platform == "win32":
            assert "not allowed" in result.lower()
        else:
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_run_command_posix_branch(self, monkeypatch):
        proc = SimpleNamespace(communicate=AsyncMock(return_value=(b"stdout data", b"stderr data")))
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "aios.runtime.adapter.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        )
        result = await RuntimeAdapter.run_command("ls -la")
        assert result == "stdout datastderr data"

    @pytest.mark.asyncio
    async def test_run_command_timeout_branch(self, monkeypatch):
        proc = SimpleNamespace(communicate=AsyncMock(), kill=Mock())
        monkeypatch.setattr(
            "aios.runtime.adapter.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        )
        monkeypatch.setattr(
            "aios.runtime.adapter.asyncio.wait_for",
            Mock(side_effect=TimeoutError("boom")),
        )
        result = await RuntimeAdapter.run_command("git status")
        assert result == "Command timed out after 120s"
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_file_success(self, monkeypatch):
        monkeypatch.setattr(
            "aios.runtime.adapter.files_plugin.read", AsyncMock(return_value="file contents")
        )
        assert await RuntimeAdapter.read_file("a.txt") == "file contents"

    @pytest.mark.asyncio
    async def test_read_file_error(self, monkeypatch):
        monkeypatch.setattr(
            "aios.runtime.adapter.files_plugin.read", AsyncMock(side_effect=RuntimeError("boom"))
        )
        assert await RuntimeAdapter.read_file("a.txt") == "Read error"

    @pytest.mark.asyncio
    async def test_write_file_success(self, monkeypatch):
        monkeypatch.setattr(
            "aios.runtime.adapter.files_plugin.write", AsyncMock(return_value="written")
        )
        assert await RuntimeAdapter.write_file("a.txt", "data") == "written"

    @pytest.mark.asyncio
    async def test_write_file_error(self, monkeypatch):
        monkeypatch.setattr(
            "aios.runtime.adapter.files_plugin.write", AsyncMock(side_effect=RuntimeError("boom"))
        )
        assert await RuntimeAdapter.write_file("a.txt", "data") == "Write error"

    @pytest.mark.asyncio
    async def test_create_sandbox(self, monkeypatch):
        sandbox = SimpleNamespace(mode="subprocess")
        monkeypatch.setattr(
            "raven.core.sandbox.SandboxConfig",
            lambda **kw: SimpleNamespace(mode="subprocess", docker_image=kw.get("docker_image")),
        )
        monkeypatch.setattr("raven.core.sandbox.Sandbox", Mock(return_value=sandbox))
        result = await RuntimeAdapter.create_sandbox(image="python:3.13")
        assert result["sandbox"] is sandbox
        assert result["mode"] == "subprocess"
        assert result["image"] == "python:3.13"

    @pytest.mark.asyncio
    async def test_search_codebase(self, monkeypatch):
        monkeypatch.setattr(
            adapter_mod, "settings", SimpleNamespace(resolved_db_path="data/test.db")
        )
        fake_retriever = SimpleNamespace(
            retrieve=AsyncMock(
                return_value=[{"text": "hello world"}, {"no_text": 1}]
            )
        )
        monkeypatch.setattr("aios.runtime.adapter.Retriever", Mock(return_value=fake_retriever))
        results = await RuntimeAdapter.search_codebase("query")
        assert results == ["hello world", str({"no_text": 1})]

    @pytest.mark.asyncio
    async def test_search_codebase_fallback_db_path(self, monkeypatch):
        monkeypatch.setattr(adapter_mod, "settings", SimpleNamespace())
        fake_retriever = SimpleNamespace(retrieve=AsyncMock(return_value=[]))
        monkeypatch.setattr("aios.runtime.adapter.Retriever", Mock(return_value=fake_retriever))
        results = await RuntimeAdapter.search_codebase("query")
        assert results == []
