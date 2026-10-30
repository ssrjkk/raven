from __future__ import annotations

import os
import re

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_SENSITIVE_KEYWORDS = frozenset({"key", "token", "secret", "password", "auth", "credential"})

_SENSITIVE_VALUES = frozenset(
    {"", "0", "false", "null", "none", "sk-or-...", "sk-ant-...", "sk-...", "change-me-in-production"}
)

# A DSN carries its credentials in the value, not in the variable's name: DATABASE_URL,
# REDIS_URL and MONGODB_URI all look harmless to a keyword list. Greedy on purpose, so a
# password containing '@' is still swallowed up to the last one before the path.
_URL_USERINFO = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.\-]*://)(?P<info>[^\s/]+)@", re.IGNORECASE)


def _mask_url_userinfo(value: str) -> str:
    match = _URL_USERINFO.match(value)
    if not match:
        return value
    info = match.group("info")
    user, separator, _password = info.partition(":")
    masked = f"{user}:***" if separator else "***"
    return f"{match.group('scheme')}{masked}@{value[match.end():]}"


def _is_sensitive(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


def _safe_val(name: str, value: str) -> str:
    if _is_sensitive(name) and value.strip() not in _SENSITIVE_VALUES:
        return f"{value[:4]}...{value[-4:]}" if len(value) > 12 else "****"
    return _mask_url_userinfo(value)


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
