from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aios.agents.orchestrator import AgentType, Orchestrator


class TestAiosOrchestrator:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent(self):
        orch = Orchestrator()
        result = await orch.dispatch("task", AgentType.PLANNER)
        assert "agent" in result

    @pytest.mark.asyncio
    async def test_autonomous_loop_structure(self):
        orch = Orchestrator()
        result = await orch.dispatch("test", AgentType.AUTONOMOUS)
        assert isinstance(result, dict)
        assert result.get("agent") == "autonomous"
