from __future__ import annotations

from typing import Any

import pytest


class TestAgentTypes:
    def test_agent_type_values(self) -> None:
        from raven.core.agents.orchestrator import AgentType

        assert AgentType.PLANNER.value == "planner"
        assert AgentType.CODER.value == "coder"
        assert AgentType.DEBUGGER.value == "debugger"
        assert AgentType.AUTONOMOUS.value == "autonomous"
        assert AgentType.PLANNER_READONLY.value == "planner_readonly"

    def test_agent_type_unique(self) -> None:
        from raven.core.agents.orchestrator import AgentType

        values = [t.value for t in AgentType]
        assert len(values) == len(set(values))

    def test_agent_result_dataclass(self) -> None:
        from raven.core.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=True, data={"key": "val"}, steps=5)
        assert r.agent == "test"
        assert r.success is True
        assert r.data == {"key": "val"}
        assert r.steps == 5

    def test_agent_result_defaults(self) -> None:
        from raven.core.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=False)
        assert r.data is None
        assert r.error is None
        assert r.steps == 0


class TestSubTask:
    def test_sub_task_defaults(self) -> None:
        from raven.core.agents.multi import SubTask
        from raven.core.agents.orchestrator import AgentType

        t = SubTask(description="do something")
        assert t.description == "do something"
        assert t.agent_type == AgentType.AUTONOMOUS
        assert t.depends_on is None
        assert t.config is None

    def test_sub_task_with_deps(self) -> None:
        from raven.core.agents.multi import SubTask
        from raven.core.agents.orchestrator import AgentType

        t = SubTask(description="step 2", agent_type=AgentType.CODER, depends_on=[0, 1])
        assert t.depends_on == [0, 1]
        assert t.agent_type == AgentType.CODER


class TestTaskResult:
    def test_task_result_dataclass(self) -> None:
        from raven.core.agents.multi import TaskResult
        from raven.core.agents.orchestrator import AgentResult

        ar = AgentResult(agent="planner", success=True)
        tr = TaskResult(index=0, description="plan", result=ar, duration=1.5)
        assert tr.index == 0
        assert tr.description == "plan"
        assert tr.result.success is True
        assert tr.duration == 1.5


class TestMultiAgentOrchestrator:
    def test_get_orchestrator_instance(self) -> None:
        from raven.core.agents.multi import get_multi_orchestrator

        orch = get_multi_orchestrator()
        assert orch is not None

    def test_orchestrator_singleton(self) -> None:
        from raven.core.agents.multi import get_multi_orchestrator

        o1 = get_multi_orchestrator()
        o2 = get_multi_orchestrator()
        assert o1 is o2

    def test_run_sequential_empty(self) -> None:
        import asyncio

        from raven.core.agents.multi import MultiAgentOrchestrator

        orch = MultiAgentOrchestrator()
        results = asyncio.run(orch.run_sequential([]))
        assert results == []

    def test_run_parallel_empty(self) -> None:
        import asyncio

        from raven.core.agents.multi import MultiAgentOrchestrator

        orch = MultiAgentOrchestrator()
        results = asyncio.run(orch.run_parallel([]))
        assert results == []

    def test_run_dag_empty(self) -> None:
        import asyncio

        from raven.core.agents.multi import MultiAgentOrchestrator

        orch = MultiAgentOrchestrator()
        results = asyncio.run(orch.run_dag([]))
        assert results == []


class TestOrchestratorDispatch:
    def test_orchestrator_create(self) -> None:
        from raven.core.agents.orchestrator import Orchestrator

        o = Orchestrator()
        assert o is not None

    def test_delegate_returns_string(self) -> None:
        import asyncio

        from raven.core.agents.orchestrator import Orchestrator

        result = asyncio.run(Orchestrator.delegate("list files in ."))
        assert isinstance(result, str)


class TestOrchestratorDispatchMethods:
    def test_dispatch_unknown_agent_returns_error(self) -> None:
        import asyncio

        from raven.core.agents.orchestrator import AgentType, Orchestrator

        o = Orchestrator()
        result = asyncio.run(o.dispatch("task", AgentType.PLANNER))
        assert result.success is False
        assert "error" in (result.error or "")
