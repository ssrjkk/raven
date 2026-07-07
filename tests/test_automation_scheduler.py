from __future__ import annotations

import asyncio

import pytest

from raven.automation.scheduler import AdvancedScheduler, ScheduledTask, TaskStatus, TriggerType


class TestAdvancedScheduler:
    def setup_method(self) -> None:
        self.scheduler = AdvancedScheduler()

    def test_add_task(self):
        task = ScheduledTask(id="t1", name="test", trigger_type=TriggerType.ONCE)
        tid = self.scheduler.add_task(task)
        assert tid == "t1"

    def test_add_task_generates_id(self):
        task = ScheduledTask(name="test", trigger_type=TriggerType.ONCE)
        tid = self.scheduler.add_task(task)
        assert tid != ""

    def test_remove_task(self):
        task = ScheduledTask(id="t1", name="test", trigger_type=TriggerType.ONCE)
        self.scheduler.add_task(task)
        assert self.scheduler.remove_task("t1") is True
        assert self.scheduler.remove_task("t1") is False

    def test_get_task(self):
        task = ScheduledTask(id="t1", name="test", trigger_type=TriggerType.ONCE)
        self.scheduler.add_task(task)
        assert self.scheduler.get_task("t1") is not None
        assert self.scheduler.get_task("nonexistent") is None

    def test_list_tasks(self):
        t1 = ScheduledTask(id="t1", name="a", trigger_type=TriggerType.ONCE)
        t2 = ScheduledTask(id="t2", name="b", trigger_type=TriggerType.INTERVAL, interval_seconds=10)
        self.scheduler.add_task(t1)
        self.scheduler.add_task(t2)
        assert len(self.scheduler.list_tasks()) == 2

    def test_cron_field_star(self):
        assert self.scheduler._cron_field_matches(5, "*")

    def test_cron_field_exact(self):
        assert self.scheduler._cron_field_matches(5, "5")

    def test_cron_field_range(self):
        assert self.scheduler._cron_field_matches(3, "1-5")
        assert not self.scheduler._cron_field_matches(6, "1-5")

    def test_cron_field_step(self):
        assert self.scheduler._cron_field_matches(4, "*/2")
        assert not self.scheduler._cron_field_matches(3, "*/2")

    @pytest.mark.asyncio
    async def test_event_emitter(self):
        results: list[str] = []

        async def handler(event: str = "", data: object = None) -> None:
            results.append(f"{event}:{data}")

        task = ScheduledTask(id="e1", name="evt", handler=handler, trigger_type=TriggerType.EVENT, event_pattern="test.event")
        self.scheduler.add_task(task)
        await self.scheduler.emit_event("test.event", "hello")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        await self.scheduler.start()
        assert self.scheduler._running is True
        await self.scheduler.stop()
        assert self.scheduler._running is False

    def test_get_stats(self):
        t1 = ScheduledTask(id="t1", name="a", trigger_type=TriggerType.CRON, cron_expression="* * * * *")
        t2 = ScheduledTask(id="t2", name="b", trigger_type=TriggerType.INTERVAL, interval_seconds=3600)
        self.scheduler.add_task(t1)
        self.scheduler.add_task(t2)
        stats = self.scheduler.get_stats()
        assert stats["total"] == 2
        assert stats["by_type"]["cron"] == 1

    @pytest.mark.asyncio
    async def test_dependency_trigger(self):
        results: list[str] = []

        async def handler() -> str:
            results.append("done")
            return "ok"

        task = ScheduledTask(id="dep1", name="dep", handler=handler, trigger_type=TriggerType.DEPENDENCY)
        self.scheduler.add_task(task)
        await self.scheduler.trigger_dependency("dep1")
        assert len(results) == 1
