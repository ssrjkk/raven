from __future__ import annotations

import sys

import pytest

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
