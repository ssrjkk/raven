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
    dangerous: bool = False
    """Whether this tool is potentially harmful; restricts default allowed roles."""
    allowed_roles: list[str] | None = None
    """Roles allowed to invoke this tool. None = any role (subject to policy overrides)."""
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


class CategoryToolRegistry:
    """Lightweight category-keyed tool registry for coding agent workflows."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Callable[..., Awaitable[Any]]]] = {
            "coding": {},
            "automation": {},
            "system": {},
        }

    def register(
        self,
        category: str,
        name: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        if category not in self._tools:
            self._tools[category] = {}
        self._tools[category][name] = handler

    def unregister(self, category: str, name: str) -> None:
        if category in self._tools and name in self._tools[category]:
            del self._tools[category][name]

    def get(self, category: str, name: str) -> Callable[..., Awaitable[Any]] | None:
        return self._tools.get(category, {}).get(name)

    def get_category(self, category: str) -> dict[str, Callable[..., Awaitable[Any]]]:
        return dict(self._tools.get(category, {}))

    def list_tools(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for category, tools in self._tools.items():
            for name in tools:
                result.append({"category": category, "name": name})
        return result

    def search(self, query: str) -> list[dict[str, str]]:
        q = query.lower()
        result: list[dict[str, str]] = []
        for category, tools in self._tools.items():
            for name in tools:
                if q in name.lower() or q in category.lower():
                    result.append({"category": category, "name": name})
        return result

    @property
    def total_count(self) -> int:
        return sum(len(tools) for tools in self._tools.values())

    @property
    def categories(self) -> list[str]:
        return list(self._tools.keys())


class ToolRegistry:
    def __init__(self, policy_store: Any = None):
        self._tools: dict[str, ToolSpec] = {}
        if policy_store is None:
            from raven.core.tools_rbac import ToolPolicyStore

            policy_store = ToolPolicyStore()
        self._policy = policy_store

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

    def effective_allowed_roles(self, name: str) -> builtins.list[str] | None:
        """Effective role allowlist for a tool: policy override > spec.allowed_roles > dangerous default."""
        override = self._policy.get(name)
        if override is not None:
            return builtins.list(override)
        spec = self._tools.get(name)
        if spec is None:
            return None
        if spec.allowed_roles is not None:
            return builtins.list(spec.allowed_roles)
        if spec.dangerous:
            return ["admin"]
        return None

    async def _run_handler(self, name: str, spec: ToolSpec, params: dict[str, Any]) -> Any:
        handler_fn = spec.handler
        if asyncio.iscoroutinefunction(handler_fn):
            return await handler_fn(**params)
        return await asyncio.to_thread(handler_fn, **params)

    async def call(self, name: str, role: str | None = None, **params: Any) -> Any:
        spec = self.get(name)
        if not spec:
            return f"[error] Unknown tool: {name}"
        if spec.handler is None:
            return f"[error] Tool {name} has no handler registered"

        denied = self._denied_by_role(name, role)
        if denied:
            return denied

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

    def _denied_by_role(self, name: str, role: str | None) -> str | None:
        if role is None:
            return None
        required = self.effective_allowed_roles(name)
        if required and role not in required:
            return f"[error] Tool '{name}' requires role {sorted(required)}; current role is '{role}'"
        return None

    @property
    def count(self) -> int:
        return len(self._tools)
