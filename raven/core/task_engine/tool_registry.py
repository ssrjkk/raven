from __future__ import annotations

import asyncio
import builtins
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from raven.core.metrics import metrics
from raven.core.tracing import get_tracer

ValidatorFn = Callable[[dict[str, Any]], str | None]
"""Returns error string if invalid, None if valid."""


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    handler: Any = None
    category: str = "general"
    timeout: int = 60
    confirm: bool = False
    """Whether this tool requires user confirmation before execution."""
    validator_fn: ValidatorFn | None = None
    """Optional validation function; returns error message or None."""

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

    async def _run_handler(self, name: str, spec: ToolSpec, params: dict[str, Any]) -> Any:
        handler_fn = spec.handler
        if asyncio.iscoroutinefunction(handler_fn):
            return await handler_fn(**params)
        return await asyncio.to_thread(handler_fn, **params)

    async def call(self, name: str, **params: Any) -> Any:
        spec = self.get(name)
        if not spec:
            return f"[error] Unknown tool: {name}"
        if spec.handler is None:
            return f"[error] Tool {name} has no handler registered"

        if spec.validator_fn:
            try:
                error = spec.validator_fn(params)
            except Exception as exc:
                logger.warning("Tool validator failed for {}: {}", name, exc)
                return f"[error] Validator failed: {exc}"
            if error:
                return f"[error] {error}"

        metrics.inc("tool_calls_total", {"tool": name, "category": spec.category})
        tracer = get_tracer()
        t0 = time.monotonic()
        with tracer.start_as_current_span("tool.call") as span:
            span.set_attribute("tool.name", name)
            span.set_attribute("tool.category", spec.category)
            try:
                result = await asyncio.wait_for(self._run_handler(name, spec, params), timeout=spec.timeout)
                elapsed = time.monotonic() - t0
                metrics.observe("tool_call_duration", elapsed, {"tool": name})
                metrics.inc("tool_calls_success_total", {"tool": name})
                return result
            except TimeoutError:
                elapsed = time.monotonic() - t0
                logger.warning("Tool {} timed out after {}s", name, spec.timeout)
                metrics.inc("tool_calls_error_total", {"tool": name, "reason": "timeout"})
                metrics.observe("tool_call_duration", elapsed, {"tool": name})
                return f"[error] Tool '{name}' timed out after {spec.timeout}s"
            except Exception as exc:
                elapsed = time.monotonic() - t0
                logger.warning("Tool {} failed: {}", name, exc)
                metrics.inc("tool_calls_error_total", {"tool": name, "reason": "exception"})
                metrics.observe("tool_call_duration", elapsed, {"tool": name})
                return f"[error] {exc}"

    @property
    def count(self) -> int:
        return len(self._tools)
