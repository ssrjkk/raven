from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from raven.core.gateway.task_orchestrator import TaskOrchestrator
from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "tasks.db")


async def _make_orchestrator(db_path: str, monkeypatch: pytest.MonkeyPatch) -> TaskOrchestrator:
    fake_db = SimpleNamespace(db_path=db_path)
    send_notification = AsyncMock(return_value=None)
    orch = TaskOrchestrator(
        fake_db,
        llm=cast("Any", None),
        mcp_pool=cast("Any", None),
        send_notification=send_notification,
    )
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="stub_tool",
            description="stub tool",
            parameters={"text": {"type": "string"}},
            handler=AsyncMock(return_value="stub result"),
        )
    )
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.create_tool_registry", lambda _mcp: registry)
    return orch


def _task_with_steps(goal: str) -> Task:
    t = Task(goal=goal, steps=[TaskStep(description="s1", tool="stub_tool", params={})])
    for s in t.steps:
        s.task_id = t.id
    return t


class TestStartRestartRecovery:
    async def test_stale_running_task_marked_failed(self, db_path: str, monkeypatch: pytest.MonkeyPatch):
        store = TaskStore(db_path)
        try:
            t = _task_with_steps("stale")
            t.status = TaskStatus.RUNNING
            t.updated_at = time.time() - 3600
            await store.save_task(t)
        finally:
            await store.close()

        orch = await _make_orchestrator(db_path, monkeypatch)
        await orch.start()
        try:
            assert orch._store is not None
            loaded = await orch._store.load_task(t.id)
            assert loaded is not None
            assert loaded.status == TaskStatus.FAILED
            assert "interrupted by gateway restart" in (loaded.error or "")
            assert t.id not in orch._tasks
        finally:
            await orch.stop()

    async def test_fresh_running_task_resumed_and_completed(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ):
        store = TaskStore(db_path)
        try:
            t = _task_with_steps("fresh")
            t.status = TaskStatus.RUNNING
            t.updated_at = time.time()
            await store.save_task(t)
        finally:
            await store.close()

        orch = await _make_orchestrator(db_path, monkeypatch)
        await orch.start()
        try:
            assert t.id in orch._tasks
            for _ in range(50):
                assert orch._store is not None
                loaded = await orch._store.load_task(t.id)
                if loaded is not None and loaded.status == TaskStatus.COMPLETED:
                    break
                await asyncio.sleep(0.05)
            assert orch._store is not None
            loaded = await orch._store.load_task(t.id)
            assert loaded is not None
            assert loaded.status == TaskStatus.COMPLETED
        finally:
            await orch.stop()

    async def test_completed_task_left_untouched(self, db_path: str, monkeypatch: pytest.MonkeyPatch):
        store = TaskStore(db_path)
        try:
            t = Task(goal="done", steps=[])
            t.status = TaskStatus.COMPLETED
            t.updated_at = time.time() - 7200
            await store.save_task(t)
        finally:
            await store.close()

        orch = await _make_orchestrator(db_path, monkeypatch)
        await orch.start()
        try:
            assert orch._store is not None
            loaded = await orch._store.load_task(t.id)
            assert loaded is not None
            assert loaded.status == TaskStatus.COMPLETED
        finally:
            await orch.stop()


class TestEmptyPlan:
    async def test_create_and_run_with_no_steps_fails(self, db_path: str, monkeypatch: pytest.MonkeyPatch):
        orch = await _make_orchestrator(db_path, monkeypatch)
        await orch.start()
        try:
            assert orch._planner is not None
            orch._planner.plan = AsyncMock(return_value=Task(goal="impossible goal"))  # type: ignore[method-assign]
            task = await orch.create_and_run("impossible goal", "user1", "test", "sess1")
            assert task.status == TaskStatus.FAILED
            assert "no steps generated" in (task.error or "")
            assert orch._store is not None
            loaded = await orch._store.load_task(task.id)
            assert loaded is not None
            assert loaded.status == TaskStatus.FAILED
            assert orch._send_notification is not None
            orch._send_notification.assert_awaited_once()  # type: ignore[attr-defined]
            notification_text = orch._send_notification.await_args.args[2]  # type: ignore[attr-defined]
            assert "Task failed" in notification_text
        finally:
            await orch.stop()


class TestFullCycle:
    async def test_create_plan_execute_complete_with_llm_plan(self, db_path: str, monkeypatch: pytest.MonkeyPatch):
        plan_json = (
            '{"summary": "stub plan", "steps": '
            '[{"description": "do the stub", "tool": "stub_tool", "params": {"text": "hi"}}]}'
        )
        llm = SimpleNamespace()

        async def stream(messages: list[dict[str, Any]]) -> Any:
            yield plan_json

        llm.complete_stream = stream
        send_notification = AsyncMock(return_value=None)
        registry = ToolRegistry()
        handler = AsyncMock(return_value="stub result")
        registry.register(
            ToolSpec(
                name="stub_tool",
                description="stub tool",
                parameters={"text": {"type": "string"}},
                handler=handler,
            )
        )
        monkeypatch.setattr(
            "raven.core.gateway.task_orchestrator.create_tool_registry", lambda _mcp: registry
        )
        orch = TaskOrchestrator(
            SimpleNamespace(db_path=db_path),
            llm=cast("Any", llm),
            mcp_pool=cast("Any", None),
            send_notification=send_notification,
        )
        await orch.start()
        try:
            task = await orch.create_and_run("do the stub", "u1", "mock", "sess1")
            assert task.status != TaskStatus.FAILED
            final: Task | None = None
            for _ in range(200):
                assert orch._store is not None
                final = await orch._store.load_task(task.id)
                if final is not None and final.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                ):
                    break
                await asyncio.sleep(0.01)
            assert final is not None
            assert final.status == TaskStatus.COMPLETED
            handler.assert_awaited_once_with(text="hi")
            for _ in range(200):
                if any("✅ Task completed" in c.args[2] for c in send_notification.call_args_list):
                    break
                await asyncio.sleep(0.01)
            texts = [c.args[2] for c in send_notification.call_args_list]
            assert any("📋 Plan" in t for t in texts)
            assert any("✅ Task completed" in t for t in texts)
        finally:
            await orch.stop()
