from __future__ import annotations

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def dream_cycle() -> str:
    from raven.core.dreaming.engine import get_dream_engine

    # the accessor raises when no engine was built; it never returns None
    try:
        eng = get_dream_engine()
    except RuntimeError:
        return "Dream engine not running"
    stats = await eng.cycle_once()
    return f"Dream cycle complete: {stats}"


async def dream_status() -> str:
    from raven.core.dreaming.engine import get_dream_engine

    try:
        eng = get_dream_engine()
    except RuntimeError:
        return "Dream engine not initialized"
    return f"Running: {eng.is_running}"


def register_dreaming_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="dream_cycle",
            description="Trigger one dream cycle — consolidates memories, detects patterns, generates skill proposals",
            parameters={},
            handler=dream_cycle,
            category="system",
        )
    )
    registry.register(
        ToolSpec(
            name="dream_status",
            description="Check if the dream engine is running",
            parameters={},
            handler=dream_status,
            category="system",
        )
    )
