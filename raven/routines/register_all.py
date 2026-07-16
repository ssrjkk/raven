from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.routine.engine import RoutineEngine
from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger
from raven.routines.actions import check_email, execute_briefing, organize_files


async def register_all_routines(engine: RoutineEngine):
    engine.register_handler(RoutineAction.SEND_BRIEFING.value, execute_briefing)
    engine.register_handler(RoutineAction.CHECK_EMAIL.value, check_email)
    engine.register_handler(RoutineAction.ORGANIZE_FILES.value, organize_files)

    examples: list[dict[str, Any]] = [
        {
            "name": "Morning Briefing",
            "action": RoutineAction.SEND_BRIEFING,
            "trigger": RoutineTrigger.SCHEDULED,
            "schedule": "08:00",
            "status": RoutineStatus.ACTIVE,
        },
        {
            "name": "Email Check (Hourly)",
            "action": RoutineAction.CHECK_EMAIL,
            "trigger": RoutineTrigger.INTERVAL,
            "schedule": "3600",
            "status": RoutineStatus.ACTIVE,
            "config": {"provider": "imap", "max_emails": 5},
        },
        {
            "name": "File Organizer (Daily)",
            "action": RoutineAction.ORGANIZE_FILES,
            "trigger": RoutineTrigger.SCHEDULED,
            "schedule": "22:00",
            "status": RoutineStatus.ACTIVE,
            "config": {"source_dir": "downloads", "dry_run": True},
        },
    ]
    existing = await engine.list_routines()
    existing_names = {r.name for r in existing}
    for cfg in examples:
        if cfg["name"] not in existing_names:
            r = Routine(
                name=cfg["name"],
                action=cfg["action"],
                trigger=cfg["trigger"],
                schedule=cfg["schedule"],
                status=cfg["status"],
                config=cfg.get("config", {}),
            )
            await engine.add_routine(r)
            logger.info("Registered default routine: {}", cfg["name"])
