from __future__ import annotations

import asyncio
from typing import Any
from datetime import datetime
from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger
from raven.core.routine.store import RoutineStore


class RoutineEngine:
    def __init__(self, store: RoutineStore):
        self._store = store
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._gateway_ref: Any = None

    def bind_gateway(self, gateway: Any):
        self._gateway_ref = gateway

    async def start(self):
        self._running = True
        routines = self._store.list_active_routines()
        for r in routines:
            self._schedule_routine(r)
        logger.info("RoutineEngine started with {} routines", len(routines))

    async def stop(self):
        self._running = False
        for rid, task in list(self._tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("RoutineEngine stopped")

    def pause_routine(self, routine_id: str):
        self._store.update_status(routine_id, RoutineStatus.PAUSED)
        task = self._tasks.pop(routine_id, None)
        if task:
            task.cancel()

    def resume_routine(self, routine_id: str):
        self._store.update_status(routine_id, RoutineStatus.ACTIVE)
        r = self._store.load_routine(routine_id)
        if r:
            self._schedule_routine(r)

    def list_routines(self) -> list[Routine]:
        return self._store.list_routines()

    def add_routine(self, routine: Routine):
        self._store.save_routine(routine)
        if routine.status == RoutineStatus.ACTIVE and self._running:
            self._schedule_routine(routine)

    def remove_routine(self, routine_id: str):
        task = self._tasks.pop(routine_id, None)
        if task:
            task.cancel()
        self._store.delete_routine(routine_id)

    def _schedule_routine(self, routine: Routine):
        if routine.id in self._tasks:
            self._tasks[routine.id].cancel()
        self._tasks[routine.id] = asyncio.create_task(
            self._run_loop(routine)
        )

    async def _run_loop(self, routine: Routine):
        while self._running:
            try:
                if routine.trigger == RoutineTrigger.INTERVAL:
                    await asyncio.sleep(int(routine.schedule))
                    await self._execute(routine)
                elif routine.trigger == RoutineTrigger.SCHEDULED:
                    now = datetime.now()
                    parts = routine.schedule.split(":")
                    target_hour = int(parts[0]) if len(parts) > 0 else 8
                    target_min = int(parts[1]) if len(parts) > 1 else 0
                    next_run = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
                    if next_run <= now:
                        next_run = next_run.replace(day=now.day + 1)
                    delay = (next_run - now).total_seconds()
                    await asyncio.sleep(delay)
                    await self._execute(routine)
                else:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Routine {} error: {}", routine.id, e)
                await asyncio.sleep(60)

    async def _execute(self, routine: Routine):
        logger.info("Executing routine: {} ({})", routine.id, routine.action.value)
        audit_logger.log(
            AuditEventType.COMMAND,
            "routine",
            routine.id,
            detail={"action": routine.action.value},
        )
        try:
            if routine.action == RoutineAction.SEND_BRIEFING:
                await self._execute_briefing(routine)
            elif routine.action == RoutineAction.SEND_MESSAGE:
                await self._execute_message(routine)
            elif routine.action == RoutineAction.CHECK_EMAIL:
                await self._execute_check_email(routine)
            elif routine.action == RoutineAction.ORGANIZE_FILES:
                await self._execute_organize_files(routine)

            routine.last_run_status = "success"
        except Exception as e:
            logger.error("Routine {} execution failed: {}", routine.id, e)
            routine.last_run_status = f"error: {e}"

    async def _execute_briefing(self, routine: Routine):
        if not self._gateway_ref:
            return
        msg = (
            f"☀️ Morning Briefing\n"
            f"Good morning! Here's your daily briefing.\n"
            f"Time: {datetime.now().strftime('%H:%M')}\n"
            f"Your routines are running smoothly."
        )
        session_id = f"{routine.channel}:{routine.user_id}:briefing"
        await self._gateway_ref._send(routine.channel, session_id, msg)

    async def _execute_message(self, routine: Routine):
        if not self._gateway_ref:
            return
        text = routine.config.get("text", "Hello from Raven!")
        session_id = f"{routine.channel}:{routine.user_id}:routine"
        await self._gateway_ref._send(routine.channel, session_id, text)

    async def _execute_check_email(self, routine: Routine):
        logger.info("Email check not yet implemented (routine {})", routine.id)

    async def _execute_organize_files(self, routine: Routine):
        logger.info("File organization not yet implemented (routine {})", routine.id)
