from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aios.agents.orchestrator import AgentType, Orchestrator  # type: ignore[attr-defined]


class TestAiosOrchestrator:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent(self):
        orch = Orchestrator()
        with patch.object(orch._inner, "dispatch", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.return_value.agent = "planner"
            mock_dispatch.return_value.success = True
            mock_dispatch.return_value.data = {}
            mock_dispatch.return_value.error = None
            result = await orch.dispatch("task", AgentType.PLANNER)
        assert "agent" in result

    @pytest.mark.asyncio
    async def test_autonomous_loop_structure(self):
        orch = Orchestrator()
        with patch.object(orch._inner, "dispatch", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.return_value.agent = "autonomous"
            mock_dispatch.return_value.success = True
            mock_dispatch.return_value.data = {}
            mock_dispatch.return_value.error = None
            result = await orch.dispatch("test", AgentType.AUTONOMOUS)
        assert isinstance(result, dict)
        assert result.get("agent") == "autonomous"
