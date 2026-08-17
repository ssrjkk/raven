from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


class TestProfiles:
    def test_profiles_contains_all(self):
        from raven.core.agents.profiles import PROFILES

        expected = {"architect", "planner", "coder", "reviewer", "debugger", "qa", "researcher", "security"}
        assert expected.issubset(PROFILES.keys())

    def test_researcher_profile(self):
        from raven.core.agents.profiles import PROFILES

        p = PROFILES["researcher"]
        assert p.name == "researcher"
        assert p.display_name == "Researcher"
        assert "research" in p.system_prompt.lower()

    def test_security_profile(self):
        from raven.core.agents.profiles import PROFILES

        p = PROFILES["security"]
        assert p.name == "security"
        assert p.display_name == "Security Engineer"
        assert "vulnerab" in p.system_prompt.lower()

    def test_resolve_profile_fallback(self):
        from raven.core.agents.profiles import resolve_profile

        p = resolve_profile("nonexistent")
        assert p.name == "coder"

    def test_resolve_profile_known(self):
        from raven.core.agents.profiles import resolve_profile

        p = resolve_profile("architect")
        assert p.name == "architect"


class TestRouting:
    def test_route_to_profile_architect(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("design the system architecture") == "architect"

    def test_route_to_profile_coder(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("implement the login feature") == "coder"

    def test_route_to_profile_reviewer(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("review the latest commit") == "reviewer"

    def test_route_to_profile_researcher(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("research codebase for deprecated APIs") == "researcher"

    def test_route_to_profile_security(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("audit this code for security vulnerabilities") == "security"

    def test_route_to_profile_debugger(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("fix the bug in login handler") == "debugger"

    def test_route_to_profile_fallback(self):
        from raven.core.agents.multi import route_to_profile

        assert route_to_profile("hello world") == "coder"


class TestIntentRouterNewProfiles:
    @pytest.mark.asyncio
    async def test_router_recognizes_researcher_keyword(self):
        from raven.core.agents.router import _keyword_classify

        result = _keyword_classify("research the codebase for patterns")
        assert result is not None
        assert result.profile == "researcher"

    @pytest.mark.asyncio
    async def test_router_recognizes_security_keyword(self):
        from raven.core.agents.router import _keyword_classify

        result = _keyword_classify("audit this code for security issues")
        assert result is not None
        assert result.profile == "security"


class TestDelegatedTask:
    def test_delegated_task_defaults(self):
        from raven.core.agents.multi import DelegatedTask

        t = DelegatedTask(description="do something", profile="coder")
        assert t.description == "do something"
        assert t.profile == "coder"
        assert t.context == {}
        assert t.depends_on is None

    def test_delegated_task_with_deps(self):
        from raven.core.agents.multi import DelegatedTask

        t = DelegatedTask(description="step 2", profile="reviewer", depends_on=[0, 1])
        assert t.depends_on == [0, 1]


class MockToolRegistry:
    def list(self):
        return []


class TestDelegationOrchestrator:
    @pytest.mark.asyncio
    async def test_run_sequential_empty(self):
        from raven.core.agents.multi import DelegationOrchestrator

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry())  # type: ignore[arg-type]
        results = await orch.run_sequential([])
        assert results == []

    @pytest.mark.asyncio
    async def test_run_parallel_empty(self):
        from raven.core.agents.multi import DelegationOrchestrator

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry())  # type: ignore[arg-type]
        results = await orch.run_parallel([])
        assert results == []

    @pytest.mark.asyncio
    async def test_run_dag_empty(self):
        from raven.core.agents.multi import DelegationOrchestrator

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry())  # type: ignore[arg-type]
        results = await orch.run_dag([])
        assert results == []

    @pytest.mark.asyncio
    async def test_run_single_task_failure_returns_error_result(self):
        from raven.core.agents.multi import DelegatedTask, DelegationOrchestrator

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        orch = DelegationOrchestrator(llm=llm, tool_registry=MockToolRegistry())  # type: ignore[arg-type]
        task = DelegatedTask(description="test", profile="coder")
        results = await orch.run_sequential([task])
        assert len(results) == 1
        assert isinstance(results[0].content, str)
        assert results[0].duration >= 0

    @pytest.mark.asyncio
    async def test_run_sequential_sets_indexes(self):
        from raven.core.agents.multi import DelegatedTask, DelegationOrchestrator, DelegationResult

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry())  # type: ignore[arg-type]

        async def fake_run_single(task: DelegatedTask) -> DelegationResult:
            return DelegationResult(
                index=0,
                description=task.description,
                profile=task.profile,
                content=f"done:{task.description}",
                success=True,
                duration=0.0,
                iterations=1,
                tokens_used=0,
                handoffs=0,
            )

        orch._run_single = fake_run_single  # type: ignore[method-assign]
        tasks = [
            DelegatedTask(description="t0", profile="coder"),
            DelegatedTask(description="t1", profile="coder"),
        ]
        results = await orch.run_sequential(tasks)
        assert [r.index for r in results] == [0, 1]
        assert [r.description for r in results] == ["t0", "t1"]

    @pytest.mark.asyncio
    async def test_run_parallel_sets_indexes(self):
        from raven.core.agents.multi import DelegatedTask, DelegationOrchestrator, DelegationResult

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry())  # type: ignore[arg-type]

        async def fake_run_single(task: DelegatedTask) -> DelegationResult:
            return DelegationResult(
                index=0,
                description=task.description,
                profile=task.profile,
                content=f"done:{task.description}",
                success=True,
                duration=0.0,
                iterations=1,
                tokens_used=0,
                handoffs=0,
            )

        orch._run_single = fake_run_single  # type: ignore[method-assign]
        tasks = [
            DelegatedTask(description="t0", profile="coder"),
            DelegatedTask(description="t1", profile="coder"),
            DelegatedTask(description="t2", profile="coder"),
        ]
        results = await orch.run_parallel(tasks)
        assert [r.index for r in results] == [0, 1, 2]
        assert [r.description for r in results] == ["t0", "t1", "t2"]

    @pytest.mark.asyncio
    async def test_run_dag_with_dependencies_returns_all_results(self):
        from raven.core.agents.multi import DelegatedTask, DelegationOrchestrator, DelegationResult

        orch = DelegationOrchestrator(llm=AsyncMock(), tool_registry=MockToolRegistry(), max_concurrent=2)  # type: ignore[arg-type]
        calls: list[str] = []

        async def fake_run_single(task: DelegatedTask) -> DelegationResult:
            calls.append(task.description)
            await asyncio.sleep(0.01)
            return DelegationResult(
                index=0,
                description=task.description,
                profile=task.profile,
                content=f"done:{task.description}",
                success=True,
                duration=0.0,
                iterations=1,
                tokens_used=0,
                handoffs=0,
            )

        orch._run_single = fake_run_single  # type: ignore[method-assign]
        tasks = [
            DelegatedTask(description="t0", profile="coder"),
            DelegatedTask(description="t1", profile="coder", depends_on=[0]),
            DelegatedTask(description="t2", profile="coder", depends_on=[0, 1]),
        ]
        results = await orch.run_dag(tasks)
        assert [r.index for r in results] == [0, 1, 2]
        assert [r.description for r in results] == ["t0", "t1", "t2"]
        assert all(r.success for r in results)
        assert calls == ["t0", "t1", "t2"]


class TestDelegateFunction:
    @pytest.mark.asyncio
    async def test_delegate_disabled_routes_to_coder(self, monkeypatch):
        from raven.core.agents.multi import delegate
        from raven.core.features import FeatureFlags

        flags = FeatureFlags()
        flags.delegation = False
        monkeypatch.setattr("raven.core.agents.multi.FeatureFlags.get", lambda: flags)

        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("stop"))

        result = await delegate("task", llm=llm, tool_registry=MockToolRegistry())  # type: ignore[arg-type]
        assert result.profile == "coder"
