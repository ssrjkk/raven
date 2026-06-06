from __future__ import annotations

from typing import Any

from raven.core.routine.engine import RoutineEngine
from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger


def register_all_routines(engine: RoutineEngine):
    examples: list[dict[str, Any]] = [
        {
            "name": "Morning Briefing",
            "action": RoutineAction.SEND_BRIEFING,
            "trigger": RoutineTrigger.SCHEDULED,
            "schedule": "08:00",
            "status": RoutineStatus.ACTIVE,
        },
    ]
    existing = engine.list_routines()
    existing_names = {r.name for r in existing}
    for cfg in examples:
        if cfg["name"] not in existing_names:
            r = Routine(
                name=cfg["name"],
                action=cfg["action"],
                trigger=cfg["trigger"],
                schedule=cfg["schedule"],
                status=cfg["status"],
            )
            engine.add_routine(r)
