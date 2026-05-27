from __future__ import annotations

from enum import Enum
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class EventType(str, Enum):
    # Message events
    MESSAGE_INBOUND = "message.inbound"
    MESSAGE_ROUTED = "message.routed"
    MESSAGE_DELIVERED = "message.delivered"

    # Session events
    SESSION_CREATED = "session.created"
    SESSION_COMPACTED = "session.compacted"
    SESSION_EXPIRED = "session.expired"

    # Agent events
    AGENT_CREATED = "agent.created"
    AGENT_RESPONSE = "agent.response"
    AGENT_ERROR = "agent.error"

    # Monitor events
    MONITOR_CHECK = "monitor.check"
    MONITOR_ALERT = "monitor.alert"
    MONITOR_STATUS_CHANGE = "monitor.status_change"

    # Task events
    TASK_PLANNED = "task.planned"
    TASK_STEP_COMPLETED = "task.step_completed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Auth events
    USER_LOGIN = "auth.user.login"
    USER_REGISTERED = "auth.user.registered"
    ROLE_CHANGED = "auth.role.changed"

    # Domain events
    ROUTINE_TRIGGERED = "routine.triggered"
    CODE_SESSION_STARTED = "code.session.started"


class EventEnvelope(BaseModel, Generic[T]):
    id: str = Field(..., description="Unique event ID (UUID)")
    type: EventType
    source: str = Field(..., description="Service name that produced the event")
    timestamp: float = Field(..., description="Unix timestamp in seconds")
    correlation_id: str = Field(default="", description="Correlation ID for tracing")
    idempotency_key: str = Field(default="", description="Idempotency key for dedup")
    data: T
    schema_version: str = "1.0"


class MessageInboundData(BaseModel):
    message_id: str
    channel: str
    user_id: str
    text: str
    session_id: str
    metadata: dict[str, str] = {}
    idempotency_key: str = ""


class MonitorAlertData(BaseModel):
    monitor_id: str
    name: str
    type: str
    target: str
    status: str
    message: str
    checked_at: float


class TaskCompletedData(BaseModel):
    task_id: str
    goal: str
    status: str
    summary: str = ""
    error: str | None = None
    steps_total: int = 0
    steps_completed: int = 0


EVENT_SCHEMA_REGISTRY: dict[EventType, type[BaseModel]] = {
    EventType.MESSAGE_INBOUND: MessageInboundData,
    EventType.MONITOR_ALERT: MonitorAlertData,
    EventType.TASK_COMPLETED: TaskCompletedData,
}
