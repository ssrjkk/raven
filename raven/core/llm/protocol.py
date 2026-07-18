from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from raven.core._json import json


class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __init__(self, id: str, name: str, arguments: dict[str, Any]):
        self.id = id
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"ToolCall(id={self.id}, name={self.name})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }

    @classmethod
    def from_openai(cls, tc: dict[str, Any]) -> ToolCall:
        args = (
            json.loads(tc["function"]["arguments"])
            if isinstance(tc["function"]["arguments"], str)
            else tc["function"]["arguments"]
        )
        return cls(id=tc["id"], name=tc["function"]["name"], arguments=args)


class LLMResponse:
    def __init__(self, content: str = "", tool_calls: list[ToolCall] | None = None, finish_reason: str = "stop"):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


class LLMProvider(ABC):
    @abstractmethod
    def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...

    @abstractmethod
    async def cleanup(self): ...


@runtime_checkable
class LLMClientProtocol(Protocol):
    """Требуемый интерфейс для failover — только complete и complete_stream."""

    async def complete(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...

    def complete_stream(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]: ...
