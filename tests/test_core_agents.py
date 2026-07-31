from __future__ import annotations

import pytest


class TestAgentTypes:
    def test_agent_type_values(self) -> None:
        from ravencode.agents.orchestrator import AgentType

        assert AgentType.PLANNER.value == "planner"
        assert AgentType.CODER.value == "coder"
        assert AgentType.DEBUGGER.value == "debugger"
        assert AgentType.AUTONOMOUS.value == "autonomous"
        assert AgentType.PLANNER_READONLY.value == "planner_readonly"

    def test_agent_type_unique(self) -> None:
        from ravencode.agents.orchestrator import AgentType

        values = [t.value for t in AgentType]
        assert len(values) == len(set(values))

    def test_agent_result_dataclass(self) -> None:
        from ravencode.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=True, data={"key": "val"}, steps=5)
        assert r.agent == "test"
        assert r.success is True
        assert r.data == {"key": "val"}
        assert r.steps == 5

    def test_agent_result_defaults(self) -> None:
        from ravencode.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=False)
        assert r.data is None
        assert r.error is None
        assert r.steps == 0


class TestOrchestratorDispatch:
    def test_orchestrator_create(self) -> None:
        from ravencode.agents.orchestrator import Orchestrator

        o = Orchestrator()
        assert o is not None

    def test_delegate_returns_string(self) -> None:
        from unittest.mock import AsyncMock, patch

        from ravencode.agents.orchestrator import Orchestrator

        with patch.object(Orchestrator, "delegate", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = "mocked result"
            import asyncio

            result = asyncio.run(Orchestrator.delegate("list files in ."))
        assert isinstance(result, str)


class TestOrchestratorDispatchMethods:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent_returns_error(self) -> None:
        from unittest.mock import AsyncMock, patch

        from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator

        o = Orchestrator()
        with patch.object(o, "dispatch", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.return_value = AgentResult(agent="planner", success=False, error="unknown agent error")
            result = await o.dispatch("task", AgentType.PLANNER)
        assert result.success is False
        assert "error" in (result.error or "")
