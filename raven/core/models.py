from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    channel: str = ""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    metadata: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "channel": self.channel,
            "role": self.role,
            "content": self.content,
            "metadata": json.dumps(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


class Session(BaseModel):
    id: str
    channel: str
    user_id: str
    agent_id: str = "default"
    agent_skills: list[str] = []
    system_prompt: str | None = None
    sandbox_policy: Any = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PluginTool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    confirm: bool = False
    """Whether this tool requires user confirmation before execution."""

    model_config = {"arbitrary_types_allowed": True}


class IncomingMessage(BaseModel):
    channel: str
    user_id: str
    session_id: str = ""
    text: str
    metadata: dict[str, Any] = {}
    priority: float = 0.0


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[dict[str, Any]] = []
    finish_reason: str = "stop"


class SessionSummary(BaseModel):
    id: str
    summary: str
    message_count: int


UserRole = Literal["user", "assistant", "system", "tool"]
