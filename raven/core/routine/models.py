from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RoutineTrigger(str, Enum):
    SCHEDULED = "scheduled"
    INTERVAL = "interval"
    MANUAL = "manual"


class RoutineAction(str, Enum):
    SEND_BRIEFING = "send_briefing"
    RUN_TASK = "run_task"
    SEND_MESSAGE = "send_message"
    CHECK_EMAIL = "check_email"
    ORGANIZE_FILES = "organize_files"


class RoutineStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class RoutineLog(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    routine_id: str = ""
    status: str = ""
    message: str = ""
    duration_ms: float = 0.0
    created_at: float = Field(default_factory=lambda: __import__("time").time())


class Routine(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    channel: str = ""
    name: str = ""
    description: str = ""
    trigger: RoutineTrigger = RoutineTrigger.SCHEDULED
    schedule: str = "0 7 * * *"
    action: RoutineAction = RoutineAction.SEND_BRIEFING
    config: dict[str, Any] = Field(default_factory=dict)
    status: RoutineStatus = RoutineStatus.ACTIVE
    last_run_at: float | None = None
    last_run_status: str = ""
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    updated_at: float = Field(default_factory=lambda: __import__("time").time())
