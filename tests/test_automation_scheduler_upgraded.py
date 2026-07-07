from __future__ import annotations

import asyncio

import pytest

from raven.automation.scheduler import (
    AdvancedScheduler,
    CronScheduler,
    EventTrigger,
    ScheduledTask,
    TaskStatus,
    TriggerType,
)


class TestCronScheduler:
    def setup_method(self) -> None:
        self.cron = CronScheduler()

    def test_schedule(self) -> None:
        self.cron.schedule("* * * * *", "t1")
        assert "t1" in self.cron._tasks

    def test_get_next_run_returns_float(self) -> None:
        result = self.cron.get_next_run("* * * * *")
        assert isinstance(result, float)

    def test_get_next_run_invalid_expression(self) -> None:
        result = self.cron.get_next_run("invalid")
        assert result > 0

    def test_field_matches_star(self) -> None:
        assert self.cron._cron_field_matches(5, "*")

    def test_field_matches_exact(self) -> None:
        assert self.cron._cron_field_matches(5, "5")
        assert not self.cron._cron_field_matches(3, "5")

    def test_field_matches_range(self) -> None:
        assert self.cron._cron_field_matches(3, "1-5")
        assert not self.cron._cron_field_matches(6, "1-5")

    def test_field_matches_step(self) -> None:
        assert self.cron._cron_field_matches(4, "*/2")
        assert not self.cron._cron_field_matches(3, "*/2")

    def test_field_matches_comma(self) -> None:
        assert self.cron._cron_field_matches(2, "1,2,3")
        assert not self.cron._cron_field_matches(4, "1,2,3")

    def test_parse_cron_returns_future(self) -> None:
        import time
        now = time.time()
        result = self.cron._parse_cron("* * * * *", now)
        assert result >= now

    def test_parse_cron_invalid_parts(self) -> None:
        import time
        now = time.time()
        result = self.cron._parse_cron("a b c", now)
        assert result == now + 3600

    def test_get_next_run_after_parse(self) -> None:
        next_run = self.cron.get_next_run("0 0 * * *")
        assert next_run > 0


class TestEventTrigger:
    def setup_method(self) -> None:
        self.trigger = EventTrigger()

    def test_subscribe(self) -> None:
        self.trigger.subscribe("test.event", "t1")
        assert "t1" in self.trigger._subscribers.get("test.event", [])

    def test_unsubscribe(self) -> None:
        self.trigger.subscribe("test.event", "t1")
        self.trigger.subscribe("test.event", "t2")
        self.trigger.unsubscribe("test.event", "t1")
        assert "t1" not in self.trigger._subscribers["test.event"]
        assert "t2" in self.trigger._subscribers["test.event"]

    def test_unsubscribe_nonexistent(self) -> None:
        self.trigger.subscribe("test.event", "t1")
        self.trigger.unsubscribe("test.event", "nonexistent")
        assert "t1" in self.trigger._subscribers["test.event"]

    @pytest.mark.asyncio
    async def test_emit_with_subscribers(self) -> None:
        self.trigger.subscribe("my.event", "t1")
        self.trigger.subscribe("my.event", "t2")
        result = await self.trigger.emit("my.event", {"key": "val"})
        assert sorted(result) == ["t1", "t2"]

    @pytest.mark.asyncio
    async def test_emit_no_subscribers(self) -> None:
        result = await self.trigger.emit("nonexistent.event")
        assert result == []

    @pytest.mark.asyncio
    async def test_emit_multiple_patterns(self) -> None:
        self.trigger.subscribe("pattern1", "t1")
        self.trigger.subscribe("pattern2", "t2")
        r1 = await self.trigger.emit("pattern1")
        r2 = await self.trigger.emit("pattern2")
        assert r1 == ["t1"]
        assert r2 == ["t2"]


class TestAdvancedSchedulerUsesDelegates:
    def setup_method(self) -> None:
        self.scheduler = AdvancedScheduler()

    def test_internal_cron_scheduler(self) -> None:
        assert isinstance(self.scheduler._cron, CronScheduler)

    def test_internal_event_trigger(self) -> None:
        assert isinstance(self.scheduler._events, EventTrigger)

    def test_parse_cron_delegates(self) -> None:
        import time
        now = time.time()
        result = self.scheduler._parse_cron("* * * * *", now)
        assert result >= now

    def test_cron_field_matches_delegates(self) -> None:
        assert self.scheduler._cron_field_matches(5, "*")
        assert self.scheduler._cron_field_matches(3, "1-5")
        assert not self.scheduler._cron_field_matches(6, "1-5")

    def test_add_event_task_subscribes(self) -> None:
        task = ScheduledTask(
            id="e1", name="evt", trigger_type=TriggerType.EVENT, event_pattern="my.event",
        )
        self.scheduler.add_task(task)
        subs = self.scheduler._events._subscribers.get("my.event", [])
        assert "e1" in subs

    def test_remove_event_task_unsubscribes(self) -> None:
        task = ScheduledTask(
            id="e1", name="evt", trigger_type=TriggerType.EVENT, event_pattern="my.event",
        )
        self.scheduler.add_task(task)
        self.scheduler.remove_task("e1")
        subs = self.scheduler._events._subscribers.get("my.event", [])
        assert "e1" not in subs

    def test_add_cron_task_uses_cron_scheduler(self) -> None:
        task = ScheduledTask(
            id="c1", name="cron", trigger_type=TriggerType.CRON, cron_expression="*/5 * * * *",
        )
        self.scheduler.add_task(task)
        assert task.next_run > 0

    @pytest.mark.asyncio
    async def test_emit_event_via_delegate(self) -> None:
        results: list[str] = []

        async def handler(event: str = "", data: object = None) -> None:
            results.append(f"{event}:{data}")

        task = ScheduledTask(
            id="e1", name="evt", handler=handler,
            trigger_type=TriggerType.EVENT, event_pattern="test.event",
        )
        self.scheduler.add_task(task)
        await self.scheduler.emit_event("test.event", "hello")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_full_scheduler_uses_both_delegates(self) -> None:
        results: list[str] = []

        async def handler(event: str = "", data: str = "") -> None:
            results.append(data)

        cron_task = ScheduledTask(
            id="c1", name="cron", handler=handler,
            trigger_type=TriggerType.CRON, cron_expression="* * * * *",
        )
        evt_task = ScheduledTask(
            id="e1", name="evt", handler=handler,
            trigger_type=TriggerType.EVENT, event_pattern="fire",
        )
        self.scheduler.add_task(cron_task)
        self.scheduler.add_task(evt_task)
        await self.scheduler.emit_event("fire", "triggered")
        assert len(results) >= 1
