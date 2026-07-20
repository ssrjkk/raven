from __future__ import annotations

import asyncio
import time

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def wait_for(seconds: float = 1.0) -> str:
    await asyncio.sleep(seconds)
    return f"Waited {seconds}s"


def get_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def register_util_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="wait",
            description="Pause execution for a given number of seconds",
            parameters={
                "seconds": {"type": "number", "description": "Seconds to wait", "required": False},
            },
            handler=wait_for,
            category="utility",
        )
    )
    registry.register(
        ToolSpec(
            name="get_timestamp",
            description="Get the current date and time",
            parameters={},
            handler=get_timestamp,
            category="utility",
        )
    )
