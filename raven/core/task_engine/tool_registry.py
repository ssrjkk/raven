from __future__ import annotations

import builtins
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from raven.core.tracing import get_tracer


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    handler: Any = None
    category: str = "general"
    timeout: int = 60

    def to_llm_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [k for k, v in self.parameters.items() if v.get("required")],
                },
            },
        }


ToolHandler = Callable[..., Awaitable[Any]]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list(self, category: str | None = None) -> list[ToolSpec]:
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def to_llm_tools(self) -> builtins.list[dict[str, Any]]:
        return [t.to_llm_tool() for t in self._tools.values()]

    async def call(self, name: str, **params: Any) -> Any:
        spec = self.get(name)
        if not spec:
            raise ValueError(f"Unknown tool: {name}")
        if spec.handler is None:
            raise ValueError(f"Tool {name} has no handler registered")
        tracer = get_tracer()
        with tracer.start_as_current_span("tool.call") as span:
            span.set_attribute("tool.name", name)
            span.set_attribute("tool.category", spec.category)
            return await spec.handler(**params)

    @property
    def count(self) -> int:
        return len(self._tools)
