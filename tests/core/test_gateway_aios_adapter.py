from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.aios_adapter import AIOSAdapter, get_aios_adapter


class _FakeOrchestrator:
    def __init__(self, captured: list[tuple[str, Any]]) -> None:
        self._captured = captured

    async def dispatch(self, task: str, agent_type: Any) -> dict[str, Any]:
        self._captured.append((task, agent_type))
        return {"ok": True, "task": task}


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import raven.core.gateway.aios_adapter as mod

    mod._adapter = None
    yield
    mod._adapter = None


def test_get_bridge_router_returns_real_router() -> None:
    from aios.api.bridge import router

    assert AIOSAdapter().get_bridge_router() is router


async def test_run_agent_valid_type(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "aios.agents.orchestrator.Orchestrator", lambda: _FakeOrchestrator(captured)
    )
    result = await AIOSAdapter().run_agent("do it", "coder")
    assert result == {"ok": True, "task": "do it"}
    assert captured[0][0] == "do it" and captured[0][1].value == "coder"


async def test_run_agent_unknown_type_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "aios.agents.orchestrator.Orchestrator", lambda: _FakeOrchestrator(captured)
    )
    await AIOSAdapter().run_agent("do it", "not-a-real-agent")
    assert captured[0][0] == "do it" and captured[0][1].value == "autonomous"


async def test_run_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aios.runtime.adapter.RuntimeAdapter",
        MagicMock(run_command=AsyncMock(return_value="stdout")),
    )
    assert await AIOSAdapter().run_command("ls") == "stdout"


async def test_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.ask = AsyncMock(return_value="answer")
    monkeypatch.setattr("ravencode.api.client.AIOSClient", lambda: client)
    assert await AIOSAdapter().ask("hi", task="review") == "answer"
    client.ask.assert_awaited_once_with("hi", task="review")


async def test_run_agent_task(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "ravencode.agents.orchestrator.Orchestrator", lambda: _FakeOrchestrator(captured)
    )
    result = await AIOSAdapter().run_agent_task("build", "planner")
    assert result == {"ok": True, "task": "build"}
    assert captured[0][0] == "build" and captured[0][1].value == "planner"


async def test_run_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = MagicMock()
    executor.run = AsyncMock(return_value="done")
    monkeypatch.setattr("ravencode.runtime.shell.ShellExecutor", lambda: executor)
    assert await AIOSAdapter().run_shell("echo hi") == "done"
    executor.run.assert_awaited_once_with("echo hi")


def test_get_aios_adapter_is_singleton() -> None:
    a = get_aios_adapter()
    assert a is get_aios_adapter()
    assert isinstance(a, AIOSAdapter)
