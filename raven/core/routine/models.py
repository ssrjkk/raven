from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RoutineAction(StrEnum):
    SEND_BRIEFING = "send_briefing"
    SEND_MESSAGE = "send_message"
    CHECK_EMAIL = "check_email"
    ORGANIZE_FILES = "organize_files"


class RoutineTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    INTERVAL = "interval"
    EVENT = "event"


class RoutineStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class RoutineLog:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    routine_id: str = ""
    status: str = ""
    message: str = ""
    duration_ms: float | None = None
    created_at: float | None = None


@dataclass
class Routine:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str = ""
    action: RoutineAction = RoutineAction.SEND_BRIEFING
    trigger: RoutineTrigger = RoutineTrigger.SCHEDULED
    schedule: str = "08:00"
    status: RoutineStatus = RoutineStatus.ACTIVE
    user_id: str = ""
    channel: str = ""
    last_run_status: str | None = None
    last_run_at: float | None = None
    config: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action.value,
            "trigger": self.trigger.value,
            "schedule": self.schedule,
            "status": self.status.value,
            "user_id": self.user_id,
            "channel": self.channel,
            "last_run_status": self.last_run_status,
            "last_run_at": self.last_run_at,
            "config": self.config,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Routine:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:16]),
            name=data.get("name", ""),
            action=RoutineAction(data.get("action", "send_briefing")),
            trigger=RoutineTrigger(data.get("trigger", "scheduled")),
            schedule=data.get("schedule", "08:00"),
            status=RoutineStatus(data.get("status", "active")),
            user_id=data.get("user_id", ""),
            channel=data.get("channel", ""),
            last_run_status=data.get("last_run_status"),
            last_run_at=data.get("last_run_at"),
            config=data.get("config", {}),
            created_at=data.get("created_at"),
        )
