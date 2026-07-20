from __future__ import annotations

import os

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_SENSITIVE_KEYWORDS = frozenset({"key", "token", "secret", "password", "auth", "credential"})

_SENSITIVE_VALUES = frozenset({"", "0", "false", "null", "none", "sk-or-...", "sk-ant-...", "sk-...", "change-me-in-production"})


def _is_sensitive(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


def _safe_val(name: str, value: str) -> str:
    if _is_sensitive(name) and value.strip() not in _SENSITIVE_VALUES:
        return f"{value[:4]}...{value[-4:]}" if len(value) > 12 else "****"
    return value


def env_get(name: str) -> str:
    val = os.environ.get(name)
    if val is None:
        return f"Environment variable {name} not set"
    return _safe_val(name, val)


def env_list() -> str:
    keys = sorted(os.environ.keys())[:50]
    lines = [f"{k}={_safe_val(k, os.environ[k])}" for k in keys]
    return "\n".join(lines)


def register_env_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="env_get",
            description="Get the value of an environment variable (values masked for sensitive vars)",
            parameters={
                "name": {"type": "string", "description": "Variable name", "required": True},
            },
            handler=env_get,
            category="system",
        )
    )
    registry.register(
        ToolSpec(
            name="env_list",
            description="List all environment variables (first 50, sensitive values masked)",
            parameters={},
            handler=env_list,
            category="system",
        )
    )
