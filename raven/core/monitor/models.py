from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
    EQ = "="
    NE = "!="
    GT = ">"
    LT = "<"
    CONTAINS = "contains"
    MATCHES = "matches"
    CHANGED = "changed"


@dataclass
class Condition:
    metric: str = ""
    operator: ConditionOperator = ConditionOperator.EQ
    value: Any = None


@dataclass
class MonitorCheck:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    monitor_id: str = ""
    status: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    triggered: bool = False
    checked_at: float | None = None
    response_time_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "monitor_id": self.monitor_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "triggered": self.triggered,
            "checked_at": self.checked_at,
            "response_time_ms": self.response_time_ms,
        }


@dataclass
class CheckResult:
    status: str = ""
    checked_at: float = 0.0
    response_time_ms: float | None = None
    triggered: bool = False
    error: str | None = None


@dataclass
class Monitor:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str = ""
    type: MonitorType = MonitorType.HTTP
    target: str = ""
    interval_seconds: int = 300
    status: MonitorStatus = MonitorStatus.ACTIVE
    conditions: list[Condition] = field(default_factory=list)
    user_id: str = ""
    channel: str = ""
    last_check: CheckResult | None = None
    notify_channels: list[str] | None = None
    cooldown_minutes: int = 30
    config: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None

    def should_notify(self) -> bool:
        if not self.last_check:
            return True
        if not self.last_check.triggered:
            return False
        elapsed = (datetime.now().timestamp() - self.last_check.checked_at) / 60
        return elapsed >= self.cooldown_minutes

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "target": self.target,
            "interval_seconds": self.interval_seconds,
            "status": self.status.value,
            "user_id": self.user_id,
            "channel": self.channel,
            "notify_channels": self.notify_channels or [],
            "cooldown_minutes": self.cooldown_minutes,
            "config": self.config,
            "created_at": self.created_at,
            "last_check": {
                "status": self.last_check.status,
                "checked_at": self.last_check.checked_at,
                "response_time_ms": self.last_check.response_time_ms,
                "triggered": self.last_check.triggered,
                "error": self.last_check.error,
            }
            if self.last_check
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Monitor:
        m = cls(
            id=data.get("id", uuid.uuid4().hex[:16]),
            name=data.get("name", ""),
            type=MonitorType(data.get("type", "http")),
            target=data.get("target", ""),
            interval_seconds=data.get("interval_seconds", 300),
            status=MonitorStatus(data.get("status", "active")),
            user_id=data.get("user_id", ""),
            channel=data.get("channel", ""),
            notify_channels=data.get("notify_channels"),
            cooldown_minutes=data.get("cooldown_minutes", 30),
            config=data.get("config", {}),
            created_at=data.get("created_at"),
        )
        lc = data.get("last_check")
        if lc:
            m.last_check = CheckResult(
                status=lc.get("status", "up"),
                checked_at=lc.get("checked_at", 0),
                response_time_ms=lc.get("response_time_ms"),
                triggered=lc.get("triggered", False),
                error=lc.get("error"),
            )
        return m
