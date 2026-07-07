from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from loguru import logger


class TriggerType(StrEnum):
    CRON = "cron"
    EVENT = "event"
    DEPENDENCY = "dependency"
    INTERVAL = "interval"
    ONCE = "once"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ScheduledTask:
    name: str
    id: str = ""
    handler: Callable[..., Awaitable[Any]] | None = None
    trigger_type: TriggerType = TriggerType.ONCE
    cron_expression: str = ""
    event_pattern: str = ""
    depends_on: list[str] = field(default_factory=list)
    interval_seconds: float = 0.0
    run_at: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0
    retry_delay: float = 1.0
    timeout: float = 300.0
    enabled: bool = True
    maintenance_windows: list[tuple[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    status: TaskStatus = TaskStatus.PENDING
    last_run: float = 0.0
    next_run: float = 0.0
    run_count: int = 0


_CRON_DEFAULT_FALLBACK = 3600
_CRON_LOOKAHEAD_DAYS = 60
_SLEEP_INTERVAL = 1


class CronScheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, str] = {}

    def schedule(self, cron_expression: str, task_id: str) -> None:
        self._tasks[task_id] = cron_expression

    def _parse_cron(self, expression: str, from_time: float = 0.0) -> float:
        now = datetime.fromtimestamp(from_time or time.time(), tz=UTC)
        parts = expression.strip().split()
        if len(parts) != 5:
            return from_time + _CRON_DEFAULT_FALLBACK

        minute_str, hour_str, dom_str, month_str, dow_str = parts
        candidates: list[datetime] = []

        base = now.replace(second=0, microsecond=0)
        for day_offset in range(_CRON_LOOKAHEAD_DAYS):
            candidate = base.replace(hour=0, minute=0) + timedelta(days=day_offset)

            if self._cron_field_matches(candidate.minute, minute_str) and \
               self._cron_field_matches(candidate.hour, hour_str) and \
               self._cron_field_matches(candidate.day, dom_str) and \
               self._cron_field_matches(candidate.month, month_str) and \
               self._cron_field_matches(candidate.isoweekday(), dow_str) and \
               candidate.timestamp() > from_time:
                    candidates.append(candidate)

        if not candidates:
            return from_time + _CRON_DEFAULT_FALLBACK
        return min(c.timestamp() for c in candidates)

    def _cron_field_matches(self, value: int, field: str) -> bool:
        if field == "*":
            return True
        for part in field.split(","):
            part = part.strip()
            if "/" in part:
                base, step = part.split("/")
                base_val = 0 if base == "*" else int(base)
                if (value - base_val) % int(step) == 0 and value >= base_val:
                    return True
            elif "-" in part:
                start, end = part.split("-")
                if int(start) <= value <= int(end):
                    return True
            elif part == str(value):
                return True
        return False

    def get_next_run(self, cron_expression: str) -> float:
        return self._parse_cron(cron_expression)


class EventTrigger:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[str]] = {}

    def subscribe(self, event_pattern: str, task_id: str) -> None:
        self._subscribers.setdefault(event_pattern, []).append(task_id)

    def unsubscribe(self, event_pattern: str, task_id: str) -> None:
        subs = self._subscribers.get(event_pattern, [])
        if task_id in subs:
            subs.remove(task_id)

    async def emit(self, event_type: str, data: Any = None) -> list[str]:
        return list(self._subscribers.get(event_type, []))


class AdvancedScheduler:
    def __init__(self) -> None:
        self._cron = CronScheduler()
        self._events = EventTrigger()
        self._tasks: dict[str, ScheduledTask] = {}
        self._handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None
        self._completed: dict[str, Any] = {}

    def register_handler(self, name: str, handler: Callable[..., Awaitable[Any]]) -> None:
        self._handlers[name] = handler

    def add_task(self, task: ScheduledTask) -> str:
        if not task.id:
            task.id = uuid.uuid4().hex[:12]
        task.next_run = self._calculate_next_run(task)
        self._tasks[task.id] = task

        if task.trigger_type == TriggerType.EVENT and task.event_pattern:
            self._events.subscribe(task.event_pattern, task.id)

        return task.id

    def remove_task(self, task_id: str) -> bool:
        task = self._tasks.pop(task_id, None)
        if task and task.trigger_type == TriggerType.EVENT and task.event_pattern:
            self._events.unsubscribe(task.event_pattern, task_id)
        return task is not None

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    def _calculate_next_run(self, task: ScheduledTask) -> float:
        now = time.time()
        if task.trigger_type == TriggerType.ONCE:
            return task.run_at or now
        if task.trigger_type == TriggerType.INTERVAL:
            return (task.last_run or now) + task.interval_seconds
        if task.trigger_type == TriggerType.CRON and task.cron_expression:
            return self._cron._parse_cron(task.cron_expression, now)
        return now

    def _parse_cron(self, expression: str, from_time: float = 0.0) -> float:
        return self._cron._parse_cron(expression, from_time)

    def _cron_field_matches(self, value: int, field: str) -> bool:
        return self._cron._cron_field_matches(value, field)

    async def emit_event(self, event_type: str, data: Any = None) -> list[Any]:
        results: list[Any] = []
        for task_id in await self._events.emit(event_type, data):
            task = self._tasks.get(task_id)
            if task and task.enabled and not self._in_maintenance_window(task):
                result = await self._run_task(task, {"event": event_type, "data": data})
                results.append(result)
        return results

    def _in_maintenance_window(self, task: ScheduledTask) -> bool:
        if not task.maintenance_windows:
            return False
        now = datetime.now(UTC)
        current_sec = now.hour * 3600 + now.minute * 60 + now.second
        current_day = now.isoweekday()
        for day_range, time_range in task.maintenance_windows:
            if day_range and current_day != int(day_range):
                continue
            if time_range and "-" in time_range:
                start_sec = self._time_to_seconds(time_range.split("-")[0])
                end_sec = self._time_to_seconds(time_range.split("-")[1])
                if start_sec <= current_sec <= end_sec:
                    return True
        return False

    def _time_to_seconds(self, time_str: str) -> int:
        parts = time_str.strip().split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:  # noqa: SIM105
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                for task in list(self._tasks.values()):
                    if self._should_skip_task(task):
                        continue
                    if task.next_run > 0 and now >= task.next_run:
                        await self._run_task(task)
                        task.last_run = now
                        task.run_count += 1
                        task.next_run = self._calculate_next_run(task)
                await asyncio.sleep(_SLEEP_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("[scheduler] loop error: {}", exc)
                await asyncio.sleep(5)

    def _should_skip_task(self, task: ScheduledTask) -> bool:
        return not task.enabled or task.trigger_type == TriggerType.DEPENDENCY or self._in_maintenance_window(task)

    async def trigger_dependency(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task or not task.enabled or task.trigger_type != TriggerType.DEPENDENCY:
            return
        if self._in_maintenance_window(task):
            return
        await self._run_task(task)
        task.last_run = time.time()
        task.run_count += 1

    async def _run_task(self, task: ScheduledTask, override_params: dict[str, Any] | None = None) -> Any:
        task.status = TaskStatus.RUNNING
        handler = task.handler or self._handlers.get(task.name)
        if handler is None:
            task.status = TaskStatus.FAILED
            logger.warning("[scheduler] no handler for task {}", task.id)
            return None

        params = dict(task.params)
        if override_params:
            params.update(override_params)

        for attempt in range(task.max_retries + 1):
            try:
                result = await asyncio.wait_for(handler(**params), timeout=task.timeout)
                task.status = TaskStatus.SUCCESS
                self._completed[task.id] = result
                return result
            except Exception as exc:
                logger.warning("[scheduler] task {} attempt {}/{} failed: {}", task.id, attempt + 1, task.max_retries + 1, exc)
                if attempt < task.max_retries:
                    await asyncio.sleep(task.retry_delay * (2 ** attempt))
                else:
                    task.status = TaskStatus.FAILED
        return None

    def get_stats(self) -> dict[str, Any]:
        total = len(self._tasks)
        enabled = sum(1 for t in self._tasks.values() if t.enabled)
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for t in self._tasks.values():
            by_type[t.trigger_type.value] = by_type.get(t.trigger_type.value, 0) + 1
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        return {"total": total, "enabled": enabled, "by_type": by_type, "by_status": by_status}
