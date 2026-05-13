from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from loguru import logger

from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus

RoutineHandler = Callable[[Routine], Awaitable[str]]


def _parse_cron(cron_expr: str) -> tuple[int, int]:
    """Parse simple cron 'min hour * * *' or 'HH:MM' into (hour, minute)."""
    cron = cron_expr.strip()
    if ":" in cron:
        parts = cron.split(":")
        return int(parts[0]), int(parts[1])
    parts = cron.split()
    if len(parts) == 5:
        return int(parts[1]), int(parts[0])
    return 7, 0


class RoutineEngine:
    def __init__(self, store, alert_dispatcher=None):
        self._store = store
        self._handlers: dict[str, RoutineHandler] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def register_handler(self, action: str, handler: RoutineHandler) -> None:
        self._handlers[action] = handler

    async def start(self) -> None:
        self._running = True
        routines = self._store.list_active()
        for r in routines:
            self._schedule_routine(r)
        logger.info("Routine engine started with {} routines", len(routines))

    async def stop(self) -> None:
        self._running = False
        for tid, task in self._tasks.items():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("Routine engine stopped")

    def add_routine(self, routine: Routine) -> None:
        self._store.save_routine(routine)
        if routine.status == RoutineStatus.ACTIVE:
            self._schedule_routine(routine)

    def remove_routine(self, routine_id: str) -> None:
        task = self._tasks.pop(routine_id, None)
        if task:
            task.cancel()
        self._store.delete_routine(routine_id)

    def pause_routine(self, routine_id: str) -> bool:
        task = self._tasks.pop(routine_id, None)
        if task:
            task.cancel()
        self._store.update_status(routine_id, RoutineStatus.PAUSED)
        return True

    def resume_routine(self, routine_id: str) -> bool:
        self._store.update_status(routine_id, RoutineStatus.ACTIVE)
        r = self._store.load_routine(routine_id)
        if r:
            self._schedule_routine(r)
            return True
        return False

    def _schedule_routine(self, routine: Routine) -> None:
        if routine.trigger.value == "interval":
            interval = int(routine.schedule)
            task = asyncio.create_task(self._run_interval(routine, interval))
            self._tasks[routine.id] = task
        elif routine.trigger.value == "scheduled":
            task = asyncio.create_task(self._run_scheduled(routine))
            self._tasks[routine.id] = task

    async def _run_interval(self, routine: Routine, interval: int) -> None:
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            refreshed = self._store.load_routine(routine.id)
            if refreshed and refreshed.status != RoutineStatus.ACTIVE:
                break
            await self._execute_routine(routine)

    async def _run_scheduled(self, routine: Routine) -> None:
        hour, minute = _parse_cron(routine.schedule)
        while self._running:
            now = time.localtime()
            next_run = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
            if next_run <= time.time():
                next_run += 86400
            wait = next_run - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            if not self._running:
                break
            refreshed = self._store.load_routine(routine.id)
            if refreshed and refreshed.status != RoutineStatus.ACTIVE:
                break
            await self._execute_routine(routine)
            await asyncio.sleep(60)

    async def _execute_routine(self, routine: Routine) -> None:
        start = time.time()
        handler = self._handlers.get(routine.action.value)
        if not handler:
            logger.warning("No handler for routine action: {}", routine.action.value)
            return

        try:
            result = await handler(routine)
            elapsed = (time.time() - start) * 1000
            log = RoutineLog(
                routine_id=routine.id, status="success",
                message=result[:500], duration_ms=elapsed,
            )
            self._store.save_log(log)
            self._store.update_last_run(routine.id, "success")
            logger.info("Routine '{}' completed in {:.0f}ms", routine.name, elapsed)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log = RoutineLog(
                routine_id=routine.id, status="error",
                message=str(e), duration_ms=elapsed,
            )
            self._store.save_log(log)
            self._store.update_last_run(routine.id, "error")
            logger.error("Routine '{}' failed: {}", routine.name, e)
