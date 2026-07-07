from __future__ import annotations

import asyncio

from raven.automation.workflow_engine import WorkflowEngine, WorkflowStep


class TestMetricsWorkflowUptime:
    def setup_method(self) -> None:
        self.engine = WorkflowEngine()

    def test_health_check_returns_healthy_when_empty(self) -> None:
        status = self.engine.health_check()
        assert status["status"] == "healthy"
        assert status["healthy"] is True
        assert status["workflows_total"] == 0

    def test_health_check_returns_healthy_after_successful_workflow(self) -> None:
        async def ok_handler(**kwargs: object) -> str:
            return "ok"

        self.engine.register_handler("ok", ok_handler)
        steps = [WorkflowStep(id="s1", name="ok")]
        asyncio.run(self.engine.run_workflow(steps))
        status = self.engine.health_check()
        assert status["healthy"] is True

    def test_health_check_detects_failures(self) -> None:
        async def failing_handler(**kwargs: object) -> str:
            msg = "intentional fail"
            raise ValueError(msg)

        self.engine.register_handler("fail", failing_handler)
        steps = [WorkflowStep(id="s1", name="fail")]
        asyncio.run(self.engine.run_workflow(steps))
        status = self.engine.health_check()
        assert status["workflows_failed"] >= 1

    def test_health_check_returns_all_fields(self) -> None:
        status = self.engine.health_check()
        expected_keys = {"status", "workflows_total", "workflows_running", "workflows_failed", "handlers_registered", "healthy"}
        assert set(status.keys()) == expected_keys

    def test_handler_count_in_health_check(self) -> None:
        async def h1(**kwargs: object) -> str:
            return "a"

        async def h2(**kwargs: object) -> str:
            return "b"

        self.engine.register_handler("a", h1)
        self.engine.register_handler("b", h2)
        status = self.engine.health_check()
        assert status["handlers_registered"] == 2

    def test_multiple_workflows_uptime_tracking(self) -> None:
        async def ok(**kwargs: object) -> str:
            return "ok"

        async def fail(**kwargs: object) -> str:
            msg = "err"
            raise ValueError(msg)

        self.engine.register_handler("ok", ok)
        self.engine.register_handler("fail", fail)

        asyncio.run(self.engine.run_workflow([WorkflowStep(id="s1", name="ok")]))
        asyncio.run(self.engine.run_workflow([WorkflowStep(id="s2", name="fail")]))
        asyncio.run(self.engine.run_workflow([WorkflowStep(id="s3", name="ok")]))

        status = self.engine.health_check()
        assert status["workflows_total"] == 3
        assert status["workflows_failed"] == 1
        assert status["healthy"] is False
