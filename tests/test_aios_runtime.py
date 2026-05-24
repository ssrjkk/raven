from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aios.runtime.adapter import RuntimeAdapter


class TestAiosRuntimeAdapter:
    @pytest.mark.asyncio
    async def test_run_command_echo(self):
        result = await RuntimeAdapter.run_command("echo hello")
        assert "hello" in result.rstrip()

    @pytest.mark.asyncio
    async def test_run_command_timeout(self):
        result = await RuntimeAdapter.run_command("ping -n 30 127.0.0.1")
        assert isinstance(result, str)
