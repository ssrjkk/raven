"""The dream tools must answer honestly when no engine exists.

`get_dream_engine()` raises RuntimeError when it was never given a MemoryManager — it never returns
None — so the `if not eng:` guards these tools shipped with were unreachable and the caller saw a
traceback instead of "Dream engine not running".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from raven.core.dreaming import engine as engine_module
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.dreaming import dream_cycle, dream_status, register_dreaming_tools


@pytest.fixture
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_engine_instance", None)


@pytest.fixture
def stub_engine(monkeypatch: pytest.MonkeyPatch) -> Any:
    stub = AsyncMock()
    stub.is_running = True
    stub.cycle_once = AsyncMock(return_value={"consolidated": 3})
    monkeypatch.setattr(engine_module, "_engine_instance", stub)
    return stub


async def test_status_without_an_engine_says_so(no_engine: None) -> None:
    assert await dream_status() == "Dream engine not initialized"


async def test_cycle_without_an_engine_says_so(no_engine: None) -> None:
    assert await dream_cycle() == "Dream engine not running"


async def test_status_reports_the_engine(no_engine: None, stub_engine: Any) -> None:
    assert await dream_status() == "Running: True"
    stub_engine.is_running = False
    assert await dream_status() == "Running: False"


async def test_cycle_runs_once_and_reports_the_stats(no_engine: None, stub_engine: Any) -> None:
    result = await dream_cycle()
    stub_engine.cycle_once.assert_awaited_once_with()
    assert result == "Dream cycle complete: {'consolidated': 3}"


async def test_the_registry_path_answers_without_an_engine(no_engine: None) -> None:
    registry = ToolRegistry()
    register_dreaming_tools(registry)
    assert await registry.call("dream_status") == "Dream engine not initialized"
    assert await registry.call("dream_cycle") == "Dream engine not running"


def test_dream_cycle_publishes_no_parameters() -> None:
    registry = ToolRegistry()
    register_dreaming_tools(registry)
    spec = registry.get("dream_cycle")
    assert spec is not None
    assert spec.parameters == {}
    assert spec.to_llm_tool()["function"]["parameters"]["properties"] == {}
