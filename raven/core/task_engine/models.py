from __future__ import annotations

import time
import uuid
from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class TaskStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    order: int = 0
    description: str = ""
    tool: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    channel: str = ""
    goal: str = ""
    plan_summary: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    steps: list[TaskStep] = Field(default_factory=list)
    current_step_index: int = 0
    result: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    scheduled_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
