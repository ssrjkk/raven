from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from prometheus_client import Counter, Histogram

F = TypeVar("F", bound=Callable[..., Any])

llm_requests_total = Counter("llm_requests_total", "Total LLM requests", ["provider", "model"])
llm_request_duration = Histogram("llm_request_duration_seconds", "LLM request duration (seconds)", ["provider", "model"])
tool_execution_total = Counter("tool_execution_total", "Total tool executions", ["tool_name"])
tool_execution_duration = Histogram("tool_execution_duration_seconds", "Tool execution duration (seconds)", ["tool_name"])
webhook_events_total = Counter("webhook_events_total", "Total webhook events", ["provider", "event_type"])
agent_steps_total = Counter("agent_steps_total", "Total agent steps", ["agent_id"])
agent_run_duration = Histogram("agent_run_duration_seconds", "Agent run duration (seconds)", ["agent_id"])


def observe_llm(provider: str, model: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            llm_requests_total.labels(provider=provider, model=model).inc()
            with llm_request_duration.labels(provider=provider, model=model).time():
                return await func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def observe_tool(tool_name: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tool_execution_total.labels(tool_name=tool_name).inc()
            with tool_execution_duration.labels(tool_name=tool_name).time():
                return await func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
