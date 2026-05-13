from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MonitorType(str, Enum):
    HTTP = "http"
    PRICE = "price"
    RSS = "rss"
    FILE = "file"
    PROCESS = "process"


class MonitorStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class ConditionOperator(str, Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    NE = "ne"
    CONTAINS = "contains"
    MATCHES = "matches"
    CHANGED = "changed"


class Condition(BaseModel):
    metric: str = ""
    operator: ConditionOperator = ConditionOperator.EQ
    value: Any = None
    label: str = ""


class MonitorCheck(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    monitor_id: str = ""
    status: str = "unknown"
    response_time_ms: float | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    triggered: bool = False
    checked_at: float = Field(default_factory=lambda: __import__("time").time())


class Monitor(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    channel: str = ""
    name: str = ""
    type: MonitorType = MonitorType.HTTP
    target: str = ""
    interval_seconds: int = 300
    status: MonitorStatus = MonitorStatus.ACTIVE
    config: dict[str, Any] = Field(default_factory=dict)
    conditions: list[Condition] = Field(default_factory=list)
    last_check: MonitorCheck | None = None
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    updated_at: float = Field(default_factory=lambda: __import__("time").time())
