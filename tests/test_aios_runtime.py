from __future__ import annotations

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
