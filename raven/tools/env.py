from __future__ import annotations

import os

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def env_get(name: str) -> str:
    val = os.environ.get(name)
    return val if val is not None else f"Environment variable {name} not set"


async def env_set(name: str, value: str) -> str:
    os.environ[name] = value
    return f"Set {name}={value[:50]}"


async def env_list() -> str:
    keys = sorted(os.environ.keys())[:50]
    lines = [f"{k}={os.environ[k][:80]}" for k in keys]
    return "\n".join(lines)


def register_env_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="env_get",
        description="Get the value of an environment variable",
        parameters={
            "name": {"type": "string", "description": "Variable name", "required": True},
        },
        handler=env_get,
        category="system",
    ))
    registry.register(ToolSpec(
        name="env_set",
        description="Set an environment variable for the current session",
        parameters={
            "name": {"type": "string", "description": "Variable name", "required": True},
            "value": {"type": "string", "description": "Variable value", "required": True},
        },
        handler=env_set,
        category="system",
    ))
    registry.register(ToolSpec(
        name="env_list",
        description="List all environment variables (first 50)",
        parameters={},
        handler=env_list,
        category="system",
    ))
