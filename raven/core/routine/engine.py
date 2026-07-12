from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger
from raven.core.routine.store import RoutineStore


class RoutineEngine:
    def __init__(self, store: RoutineStore):
        self._store = store
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._gateway_ref: Any = None

    def register_handler(self, action: str, handler: Callable[..., Any]):
        self._handlers[action] = handler

    async def start(self):
        self._running = True
        routines = self._store.list_active()
        for r in routines:
            self._schedule_routine(r)
        logger.info("RoutineEngine started with {} routines", len(routines))

    async def stop(self):
        self._running = False
        for _rid, task in list(self._tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        logger.info("RoutineEngine stopped")

    def pause_routine(self, routine_id: str) -> bool:
        r = self._store.load_routine(routine_id)
        if not r:
            return False
        self._store.update_status(routine_id, RoutineStatus.PAUSED)
        task = self._tasks.pop(routine_id, None)
        if task:
            task.cancel()
        return True

    def resume_routine(self, routine_id: str) -> bool:
        r = self._store.load_routine(routine_id)
        if not r:
            return False
        self._store.update_status(routine_id, RoutineStatus.ACTIVE)
        if self._running:
            self._schedule_routine(r)
        return True

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
            self._run_loop(routine),
        )

    async def _run_loop(self, routine: Routine):
        while self._running:
            try:
                if routine.trigger == RoutineTrigger.INTERVAL:
                    await asyncio.sleep(int(routine.schedule))
                    await self._execute_routine(routine)
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
                    await self._execute_routine(routine)
                else:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Routine {} loop error: {}", routine.id, e)
                await asyncio.sleep(60)

    async def _execute_routine(self, routine: Routine):
        start = time.time()
        logger.info("Executing routine: {} ({})", routine.id, routine.action.value)
        await audit_logger.log(
            AuditEventType.COMMAND,
            "routine",
            routine.id,
            detail={"action": routine.action.value},
        )
        try:
            handler = self._handlers.get(routine.action.value)
            if handler:
                result = await handler(routine)
            elif routine.action == RoutineAction.SEND_BRIEFING:
                result = await self._execute_briefing(routine)
            elif routine.action == RoutineAction.SEND_MESSAGE:
                result = await self._execute_message(routine)
            elif routine.action == RoutineAction.CHECK_EMAIL:
                result = await self._execute_email_check(routine)
            elif routine.action == RoutineAction.ORGANIZE_FILES:
                result = await self._execute_file_organization(routine)
            else:
                result = f"Unknown action: {routine.action.value}"

            duration = (time.time() - start) * 1000
            log = RoutineLog(
                routine_id=routine.id,
                status="success",
                message=str(result),
                duration_ms=duration,
                created_at=time.time(),
            )
            self._store.save_log(log)
            self._store.update_last_run(routine.id, "success")
            routine.last_run_status = "success"
            routine.last_run_at = time.time()

        except Exception as e:
            duration = (time.time() - start) * 1000
            log = RoutineLog(
                routine_id=routine.id,
                status="error",
                message=str(e),
                duration_ms=duration,
                created_at=time.time(),
            )
            self._store.save_log(log)
            self._store.update_last_run(routine.id, f"error: {e}")
            routine.last_run_status = f"error: {e}"
            routine.last_run_at = time.time()
            logger.error("Routine {} execution failed: {}", routine.id, e)

    async def _execute_email_check(self, routine: Routine) -> str:
        try:
            from raven.core.email_api import _get_config
            config = _get_config()
            if not config.get("imap_host"):
                return "Email check skipped: no IMAP configured"

            import imaplib

            mail = imaplib.IMAP4_SSL(config["imap_host"], int(config.get("imap_port", "993")))
            mail.login(config["imap_user"], config["imap_pass"])
            mail.select("INBOX")

            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                return "Failed to search inbox"

            unread_ids = messages[0].split() if messages[0] else []
            count = len(unread_ids)
            mail.logout()

            if count > 0 and self._gateway_ref:
                session_id = f"{routine.channel}:{routine.user_id}:email"
                await self._gateway_ref._send(
                    routine.channel, session_id,
                    f"You have {count} unread email(s) in your inbox."
                )

            return f"Email check complete: {count} unread messages"
        except Exception as e:
            return f"Email check failed: {e}"

    async def _execute_file_organization(self, routine: Routine) -> str:
        import shutil
        from pathlib import Path

        workspace = Path("workspace")
        organized = 0

        rules = {
            ".txt": "text", ".md": "docs", ".json": "data",
            ".csv": "data", ".xml": "data", ".yaml": "config",
            ".yml": "config", ".py": "code", ".js": "code",
            ".ts": "code", ".jpg": "images", ".jpeg": "images",
            ".png": "images", ".gif": "images", ".svg": "images",
            ".pdf": "documents", ".doc": "documents", ".docx": "documents",
            ".xls": "documents", ".xlsx": "documents",
        }

        if not workspace.exists():
            return "No workspace directory found"

        for item in workspace.iterdir():
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            folder_name = rules.get(ext)
            if not folder_name:
                continue
            target_dir = workspace / folder_name
            target_dir.mkdir(exist_ok=True)
            target_path = target_dir / item.name
            if not target_path.exists():
                shutil.move(str(item), str(target_path))
                organized += 1

        if organized > 0 and self._gateway_ref:
            session_id = f"{routine.channel}:{routine.user_id}:organize"
            await self._gateway_ref._send(
                routine.channel, session_id,
                f"File organization complete: moved {organized} file(s) into categorized folders."
            )

        return f"File organization complete: {organized} files organized"

    async def _execute_briefing(self, routine: Routine) -> str:
        if not self._gateway_ref:
            return "No gateway bound"
        msg = (
            f"Morning Briefing\n"
            f"Good morning! Here's your daily briefing.\n"
            f"Time: {datetime.now().strftime('%H:%M')}\n"
            f"Your routines are running smoothly."
        )
        session_id = f"{routine.channel}:{routine.user_id}:briefing"
        await self._gateway_ref._send(routine.channel, session_id, msg)
        return "Briefing sent"

    async def _execute_message(self, routine: Routine) -> str:
        if not self._gateway_ref:
            return "No gateway bound"
        text = routine.config.get("text", "Hello from Raven!")
        session_id = f"{routine.channel}:{routine.user_id}:routine"
        await self._gateway_ref._send(routine.channel, session_id, text)
        return f"Message sent: {text[:100]}"
