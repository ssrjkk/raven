from __future__ import annotations

import pytest

from raven.automation.workflow_engine import (
    WorkflowEngine, WorkflowStep, StepStatus, WorkflowStatus, get_workflow_engine,
)


class TestWorkflowStep:
    def test_create_step(self):
        s = WorkflowStep(id="s1", name="test", depends_on=[], max_retries=2)
        assert s.id == "s1"
        assert s.name == "test"
        assert s.max_retries == 2
        assert s.timeout == 300.0

    def test_defaults(self):
        s = WorkflowStep(id="s1", name="test")
        assert s.depends_on == []
        assert s.max_retries == 0
        assert s.retry_delay == 1.0


class TestWorkflowEngine:
    @pytest.mark.asyncio
    async def test_run_single_step(self):
        engine = WorkflowEngine()

        async def echo(msg: str = "") -> str:
            return f"echo: {msg}"

        steps = [WorkflowStep(id="s1", name="echo", handler=echo, params={"msg": "hello"})]
        result = await engine.run_workflow(steps)
        assert result.status == WorkflowStatus.SUCCESS
        assert result.steps["s1"].status == StepStatus.SUCCESS
        assert result.steps["s1"].output == "echo: hello"

    @pytest.mark.asyncio
    async def test_run_sequential_steps(self):
        engine = WorkflowEngine()

        async def step_a() -> str:
            return "a_done"

        async def step_b(a: str = "") -> str:
            return f"b_done_with_{a}"

        steps = [
            WorkflowStep(id="a", name="Step A", handler=step_a),
            WorkflowStep(id="b", name="Step B", handler=step_b, depends_on=["a"]),
        ]
        result = await engine.run_workflow(steps)
        assert result.status == WorkflowStatus.SUCCESS
        assert result.steps["b"].output == "b_done_with_a_done"

    @pytest.mark.asyncio
    async def test_step_failure(self):
        engine = WorkflowEngine()

        async def fail() -> str:
            raise ValueError("oops")

        steps = [WorkflowStep(id="s1", name="fail", handler=fail, max_retries=0)]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.FAILED
        assert "oops" in (result.steps["s1"].error or "")

    @pytest.mark.asyncio
    async def test_conditional_skip(self):
        engine = WorkflowEngine()

        async def dummy() -> str:
            return "done"

        steps = [WorkflowStep(id="s1", name="dummy", handler=dummy, condition="False")]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_conditional_run(self):
        engine = WorkflowEngine()

        async def dummy() -> str:
            return "done"

        steps = [WorkflowStep(id="s1", name="dummy", handler=dummy, condition="True")]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_retry_success(self):
        engine = WorkflowEngine()
        attempt_count = 0

        async def flaky() -> str:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("not yet")
            return "success"

        steps = [WorkflowStep(id="s1", name="flaky", handler=flaky, max_retries=3, retry_delay=0.1)]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.SUCCESS
        assert result.steps["s1"].output == "success"

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        engine = WorkflowEngine()

        async def always_fail() -> str:
            raise ValueError("always")

        steps = [WorkflowStep(id="s1", name="fail", handler=always_fail, max_retries=1, retry_delay=0.1)]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_handler(self):
        engine = WorkflowEngine()
        steps = [WorkflowStep(id="s1", name="unknown")]
        result = await engine.run_workflow(steps)
        assert result.steps["s1"].status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        engine = WorkflowEngine()
        assert engine.list_workflows() == []

        async def dummy() -> str:
            return "ok"

        steps = [WorkflowStep(id="s1", name="dummy", handler=dummy)]
        await engine.run_workflow(steps)
        assert len(engine.list_workflows()) == 1

    @pytest.mark.asyncio
    async def test_get_result(self):
        engine = WorkflowEngine()

        async def dummy() -> str:
            return "ok"

        steps = [WorkflowStep(id="s1", name="dummy", handler=dummy)]
        result = await engine.run_workflow(steps)
        loaded = engine.get_result(result.workflow_id)
        assert loaded is not None
        assert loaded.status == WorkflowStatus.SUCCESS

    def test_get_workflow_engine_singleton(self):
        e1 = get_workflow_engine()
        e2 = get_workflow_engine()
        assert e1 is e2
