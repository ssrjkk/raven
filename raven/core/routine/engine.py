from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.periodic_engine import PeriodicEngine
from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger
from raven.core.routine.store import RoutineStore

_running_engine: RoutineEngine | None = None


def register_routine_engine(engine: RoutineEngine | None) -> None:
    global _running_engine
    _running_engine = engine


def get_routine_engine() -> RoutineEngine | None:
    return _running_engine


class RoutineEngine(PeriodicEngine[Routine, RoutineStatus, RoutineStore]):
    def __init__(self, store: RoutineStore):
        super().__init__(store)
        self._gateway_ref: Any = None

    async def add_routine(self, routine: Routine):
        await self.add_item(routine)

    async def remove_routine(self, routine_id: str):
        await self.remove_item(routine_id)

    async def pause_routine(self, routine_id: str) -> bool:
        return await self.pause_item(routine_id)

    async def resume_routine(self, routine_id: str) -> bool:
        return await self.resume_item(routine_id)

    async def list_routines(self, limit: int = 50, offset: int = 0) -> list[Routine]:
        return await self._store.list_routines(limit=limit, offset=offset)

    async def _run_loop(self, routine: Routine):
        while self._running:
            try:
                if routine.trigger == RoutineTrigger.INTERVAL:
                    await asyncio.sleep(int(routine.schedule))
                    await self._execute_routine(routine)
                elif routine.trigger == RoutineTrigger.SCHEDULED:
                    delay = self._delay_until(routine.schedule)
                    await asyncio.sleep(delay)
                    await self._execute_routine(routine)
                else:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Routine {} loop error: {}", routine.id, e)
                await asyncio.sleep(60)

    async def _run_item(self, routine: Routine) -> Any:
        return await self._execute_routine(routine)

    async def _list_active(self) -> list[Routine]:
        return await self._store.list_active()

    async def _load_item(self, item_id: str) -> Routine | None:
        return await self._store.load_routine(item_id)

    async def _save_item(self, item: Routine):
        await self._store.save_routine(item)

    async def _delete_item(self, item_id: str):
        await self._store.delete_routine(item_id)

    async def _update_status(self, item_id: str, status: RoutineStatus):
        await self._store.update_status(item_id, status)

    def _get_item_id(self, item: Routine) -> str:
        return item.id

    def _is_active(self, item: Routine) -> bool:
        return item.status == RoutineStatus.ACTIVE

    def _get_interval(self, item: Routine) -> int | float:
        return int(item.schedule)

    def _paused_status(self) -> RoutineStatus:
        return RoutineStatus.PAUSED

    def _active_status(self) -> RoutineStatus:
        return RoutineStatus.ACTIVE

    @staticmethod
    def _next_run_time(schedule: str, now: datetime | None = None) -> datetime:
        parts = schedule.split(":")
        target_hour = int(parts[0]) if len(parts) > 0 and parts[0] else 8
        target_min = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        current = now or datetime.now(UTC)
        next_run = current.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
        if next_run <= current:
            next_run = next_run + timedelta(days=1)
        return next_run

    @classmethod
    def _delay_until(cls, schedule: str, now: datetime | None = None) -> float:
        current = now or datetime.now(UTC)
        return max((cls._next_run_time(schedule, current) - current).total_seconds(), 0.0)

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
            await self._store.save_log(log)
            await self._store.update_last_run(routine.id, "success")
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
            await self._store.save_log(log)
            await self._store.update_last_run(routine.id, f"error: {e}")
            routine.last_run_status = f"error: {e}"
            routine.last_run_at = time.time()
            logger.error("Routine {} execution failed: {}", routine.id, e)

    async def _execute_email_check(self, routine: Routine) -> str:
        try:
            from raven.core.email_api import _get_config

            config = _get_config()
            if not config.get("imap_host"):
                return "Email check skipped: no IMAP configured"

            def _sync_check() -> int:
                import imaplib

                mail = imaplib.IMAP4_SSL(config["imap_host"], int(config.get("imap_port", "993")))
                mail.login(config["imap_user"], config["imap_pass"])
                mail.select("INBOX")
                try:
                    status, messages = mail.search(None, "UNSEEN")
                    if status != "OK":
                        return -1
                    return len(messages[0].split()) if messages[0] else 0
                finally:
                    mail.logout()

            count = await asyncio.to_thread(_sync_check)
            if count < 0:
                return "Failed to search inbox"

            if count > 0 and self._gateway_ref:
                session_id = f"{routine.channel}:{routine.user_id}:email"
                await self._gateway_ref._send(
                    routine.channel, session_id, f"You have {count} unread email(s) in your inbox."
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
            ".txt": "text",
            ".md": "docs",
            ".json": "data",
            ".csv": "data",
            ".xml": "data",
            ".yaml": "config",
            ".yml": "config",
            ".py": "code",
            ".js": "code",
            ".ts": "code",
            ".jpg": "images",
            ".jpeg": "images",
            ".png": "images",
            ".gif": "images",
            ".svg": "images",
            ".pdf": "documents",
            ".doc": "documents",
            ".docx": "documents",
            ".xls": "documents",
            ".xlsx": "documents",
        }

        if not workspace.exists():
            return "No workspace directory found"

        for item in sorted(workspace.iterdir()):
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
                routine.channel,
                session_id,
                f"File organization complete: moved {organized} file(s) into categorized folders.",
            )

        return f"File organization complete: {organized} files organized"

    async def _execute_briefing(self, routine: Routine) -> str:
        if not self._gateway_ref:
            return "No gateway bound"
        msg = (
            f"Morning Briefing\n"
            f"Good morning! Here's your daily briefing.\n"
            f"Time: {datetime.now(UTC).strftime('%H:%M')}\n"
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
