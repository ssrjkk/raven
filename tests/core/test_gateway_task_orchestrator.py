from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.task_orchestrator import TaskOrchestrator
from raven.core.task_engine.models import Task, TaskStatus, TaskStep


def _orch(
    *,
    send: Any = None,
    event_bus: Any = None,
) -> TaskOrchestrator:
    db = SimpleNamespace(db_path=":memory:")
    return TaskOrchestrator(
        db,
        MagicMock(),
        MagicMock(),
        send_notification=send,
        event_bus=event_bus,
    )


def _store() -> MagicMock:
    s = MagicMock()
    s.save_task = AsyncMock()
    s.list_tasks = AsyncMock(return_value=[])
    s.update_status = AsyncMock()
    s.load_task = AsyncMock(return_value=None)
    s.close = AsyncMock()
    return s


def _runner() -> MagicMock:
    r = MagicMock()
    r.submit = AsyncMock()
    r.wait = AsyncMock()
    r.shutdown = AsyncMock()
    r.reset_inflight_steps = AsyncMock()
    return r


# ── _format_result ────────────────────────────────────────────────


def test_format_result_completed() -> None:
    orch = _orch()
    task = Task(
        id="t1",
        status=TaskStatus.COMPLETED,
        steps=[TaskStep(description="do thing", result={"ok": 1}), TaskStep(description="empty")],
    )
    out = orch._format_result(task)
    assert "Task completed!" in out
    assert "do thing" in out
    assert "empty" not in out


def test_format_result_failed() -> None:
    orch = _orch()
    out = orch._format_result(Task(id="t1", status=TaskStatus.FAILED, error="boom"))
    assert out == "❌ Task failed: boom"


def test_format_result_failed_no_error() -> None:
    orch = _orch()
    out = orch._format_result(Task(id="t1", status=TaskStatus.FAILED))
    assert "Unknown error" in out


def test_format_result_cancelled() -> None:
    orch = _orch()
    assert orch._format_result(Task(id="t1", status=TaskStatus.CANCELLED)) == "🚫 Task cancelled"


def test_format_result_other_status() -> None:
    orch = _orch()
    assert orch._format_result(Task(id="t1", status=TaskStatus.PAUSED)) == "Task status: paused"


# ── get/list/notify ───────────────────────────────────────────────


def test_get_task() -> None:
    orch = _orch()
    t = Task(id="t1")
    orch._tasks["t1"] = t
    assert orch.get_task("t1") is t
    assert orch.get_task("missing") is None


async def test_list_tasks() -> None:
    orch = _orch()
    orch._tasks["t1"] = Task(id="t1")
    tasks = await orch.list_tasks()
    assert [t.id for t in tasks] == ["t1"]


async def test_notify_without_sender_is_noop() -> None:
    orch = _orch(send=None)
    await orch._notify("c", "s", "hi")  # must not raise


async def test_notify_calls_sender() -> None:
    sender = AsyncMock()
    orch = _orch(send=sender)
    await orch._notify("chan", "sid", "text")
    sender.assert_awaited_once_with("chan", "sid", "text")


# ── create_and_run ────────────────────────────────────────────────


async def test_create_and_run_not_started() -> None:
    orch = _orch()
    with pytest.raises(RuntimeError, match="not started"):
        await orch.create_and_run("goal", "u1", "web")


async def test_create_and_run_planning_error() -> None:
    sender = AsyncMock()
    orch = _orch(send=sender)
    orch._store = _store()
    orch._runner = _runner()
    orch._planner = MagicMock()
    orch._planner.plan = AsyncMock(side_effect=RuntimeError("llm down"))
    with pytest.raises(RuntimeError, match="llm down"):
        await orch.create_and_run("goal", "u1", "web", session_id="s1")
    assert "Task planning failed" in sender.await_args_list[-1].args[2]


async def test_create_and_run_without_a_session_notifies_nothing() -> None:
    """A task submitted over HTTP has no chat to report to; the send must not be attempted."""
    sender = AsyncMock()
    orch = _orch(send=sender)
    orch._store = _store()
    orch._runner = _runner()
    orch._planner = MagicMock()
    orch._planner.plan = AsyncMock(side_effect=RuntimeError("llm down"))
    with pytest.raises(RuntimeError, match="llm down"):
        await orch.create_and_run("goal", "u1", "ops")
    sender.assert_not_awaited()


async def test_create_and_run_no_steps() -> None:
    sender = AsyncMock()
    orch = _orch(send=sender)
    store = _store()
    orch._store = store
    orch._runner = _runner()
    orch._planner = MagicMock()
    orch._planner.plan = AsyncMock(return_value=Task(id="t1", steps=[]))
    result = await orch.create_and_run("goal", "u1", "web", session_id="s1")
    assert result.status is TaskStatus.FAILED
    assert result.error is not None and "no steps" in result.error
    store.save_task.assert_awaited_once_with(result)
    assert "Task failed" in sender.await_args_list[-1].args[2]


async def test_create_and_run_happy() -> None:
    sender = AsyncMock()
    orch = _orch(send=sender)
    orch._store = _store()
    runner = _runner()
    done = Task(id="t1", status=TaskStatus.COMPLETED, steps=[TaskStep(description="a", result="r")])
    runner.wait = AsyncMock(return_value=done)
    orch._runner = runner
    planned = Task(id="t1", status=TaskStatus.PENDING, steps=[TaskStep(description="a"), TaskStep(description="b")])
    orch._planner = MagicMock()
    orch._planner.plan = AsyncMock(return_value=planned)

    task = await orch.create_and_run("goal", "u1", "web", "sid")
    assert task is planned
    runner.submit.assert_awaited_once_with(planned)
    texts = [c.args[2] for c in sender.await_args_list]
    assert any("📋 Plan:" in t for t in texts)
    # drain the background notify task so it runs to completion
    for bg in list(orch._bg_tasks):
        await bg


# ── _wait_and_notify ──────────────────────────────────────────────


async def test_wait_and_notify_not_started() -> None:
    orch = _orch()
    with pytest.raises(RuntimeError, match="not started"):
        await orch._wait_and_notify(Task(id="t1"), "web", "sid")


async def test_wait_and_notify_happy_with_event_bus() -> None:
    sender = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    orch = _orch(send=sender, event_bus=bus)
    runner = _runner()
    runner.wait = AsyncMock(return_value=Task(id="t1", status=TaskStatus.COMPLETED, steps=[]))
    orch._runner = runner
    await orch._wait_and_notify(Task(id="t1"), "web", "sid")
    bus.publish.assert_awaited_once_with(
        "task.completed", task_id="t1", status="completed", channel="web", session_id="sid"
    )
    assert "Task completed" in sender.await_args_list[-1].args[2]


async def test_wait_and_notify_error_path() -> None:
    sender = AsyncMock()
    orch = _orch(send=sender)
    runner = _runner()
    runner.wait = AsyncMock(side_effect=RuntimeError("runner blew up"))
    orch._runner = runner
    await orch._wait_and_notify(Task(id="t1"), "web", "sid")
    assert "Task error: runner blew up" in sender.await_args_list[-1].args[2]


# ── start / stop ──────────────────────────────────────────────────


async def test_start_marks_stale_and_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = _orch()
    store = _store()
    old = Task(id="stale", status=TaskStatus.RUNNING, updated_at=time.time() - 10000)
    fresh_running = Task(id="run", status=TaskStatus.RUNNING, updated_at=time.time(), current_step_index=2)
    fresh_pending = Task(id="pend", status=TaskStatus.PENDING, updated_at=time.time())
    store.list_tasks = AsyncMock(
        side_effect=[
            [old, fresh_pending],  # pending query
            [fresh_running],  # running query
        ]
    )
    full = Task(id="run", status=TaskStatus.RUNNING, steps=[TaskStep()])
    store.load_task = AsyncMock(return_value=full)
    runner = _runner()

    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskStore", lambda path: store)
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.create_task_tool_registry", lambda pool: MagicMock())
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskPlanner", lambda tools: MagicMock())
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskRunner", lambda s, tools: runner)

    await orch.start()

    store.update_status.assert_awaited_once_with("stale", TaskStatus.FAILED, error="Task interrupted by gateway restart")
    runner.reset_inflight_steps.assert_awaited_once_with(full)
    submitted = {c.args[0].id for c in runner.submit.await_args_list}
    assert submitted == {"run", "pend"}
    assert set(orch._tasks.keys()) == {"run", "pend"}


async def test_start_resume_failure_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = _orch()
    store = _store()
    t = Task(id="bad", status=TaskStatus.PENDING, updated_at=time.time())
    store.list_tasks = AsyncMock(side_effect=[[t], []])
    runner = _runner()
    runner.submit = AsyncMock(side_effect=RuntimeError("submit down"))

    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskStore", lambda path: store)
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.create_task_tool_registry", lambda pool: MagicMock())
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskPlanner", lambda tools: MagicMock())
    monkeypatch.setattr("raven.core.gateway.task_orchestrator.TaskRunner", lambda s, tools: runner)

    await orch.start()
    assert store.update_status.await_args is not None
    assert store.update_status.await_args.args[0] == "bad"
    assert store.update_status.await_args.args[1] is TaskStatus.FAILED
    # the implementation keeps the task tracked even after a failed resume
    assert "bad" in orch._tasks


async def test_stop_shuts_down_runner_and_store() -> None:
    orch = _orch()
    orch._tasks["t1"] = Task(id="t1")
    runner = _runner()
    store = _store()
    orch._runner = runner
    orch._store = store
    await orch.stop()
    runner.shutdown.assert_awaited_once()
    store.close.assert_awaited_once()
    assert orch._store is None
    assert orch._runner is None
    assert orch._planner is None
    assert orch._tasks == {}


async def test_stop_cancels_background_tasks() -> None:
    orch = _orch()

    async def _forever() -> None:
        await asyncio.sleep(3600)

    bg = asyncio.create_task(_forever())
    orch._bg_tasks.add(bg)
    await orch.stop()
    assert bg.cancelled()
    assert orch._bg_tasks == set()
