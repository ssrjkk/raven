"""Cancellation and timeout accounting in the task engine.

Each test here reproduces a defect that was measured on the previous implementation:
a cancel from another runner was a no-op the owner overwrote, and a timed-out step was
retried three times even though its handler was still running.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.runner import TaskRunner
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def store(tmp_path: Path):
    s = TaskStore(str(tmp_path / "tasks.db"))
    yield s
    await s.close()


def registry_with(handler, *, timeout: int = 30, **spec_kwargs) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="step", description="x", parameters={}, handler=handler, timeout=timeout, **spec_kwargs)
    )
    return reg


def one_step_task(store: TaskStore) -> Task:
    task = Task(goal="g", user_id="u")
    task.steps = [TaskStep(task_id="", order=0, description="d", tool="step", params={})]
    for step in task.steps:
        step.task_id = task.id
    return task


async def test_a_cancel_from_another_runner_stops_the_owner(store: TaskStore) -> None:
    """The CLI and POST /api/task/{id}/cancel each build their own TaskRunner."""
    entered = threading.Event()

    def blocking_handler() -> str:
        entered.set()
        time.sleep(30)
        return "finished anyway"

    owner = TaskRunner(store, registry_with(blocking_handler))
    asker = TaskRunner(store, registry_with(blocking_handler))
    task = one_step_task(store)

    await owner.submit(task)
    await asyncio.to_thread(entered.wait, 5)
    assert await asker.cancel(task.id) is True

    settled = await owner.wait(task.id, timeout=15)
    assert settled is not None
    assert settled.status == TaskStatus.CANCELLED, "the owner overwrote the cancellation"
    assert settled.steps[0].status != TaskStatus.RUNNING, "a step is left in flight under a cancelled task"
    assert task.id not in owner._running


async def test_a_late_completion_cannot_overwrite_a_cancel(store: TaskStore) -> None:
    async def quick() -> str:
        return "done"

    runner = TaskRunner(store, registry_with(quick))
    task = one_step_task(store)
    await runner.submit(task)
    await runner.wait(task.id, timeout=10)

    await store.update_status(task.id, TaskStatus.CANCELLED)
    task.status = TaskStatus.COMPLETED
    task.result = "arrived late"
    await store.save_task(task)

    reloaded = await store.load_task(task.id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.CANCELLED


async def test_a_cancelled_task_that_never_ran_reports_one_cancellation(store: TaskStore) -> None:
    from raven.core.metrics import metrics

    calls: list[str] = []

    async def counted() -> str:
        calls.append("called")
        return "done"

    metrics.clear()
    runner = TaskRunner(store, registry_with(counted))
    task = one_step_task(store)
    await runner.submit(task)
    assert await runner.cancel(task.id) is True
    settled = await runner.wait(task.id, timeout=10)

    assert settled is not None
    assert settled.status == TaskStatus.CANCELLED
    assert metrics.snapshot().get("raven_task_cancelled_total") == 1


async def test_a_timeout_is_not_retried(store: TaskStore) -> None:
    """A timed-out handler keeps running; a second attempt stacks a second one onto it."""
    attempts: list[float] = []

    def slow() -> str:
        attempts.append(time.monotonic())
        time.sleep(3)
        return "done"

    runner = TaskRunner(store, registry_with(slow, timeout=1))
    runner.STEP_RETRY_BACKOFF = 0.01
    task = one_step_task(store)

    await runner.submit(task)
    settled = await runner.wait(task.id, timeout=20)

    assert settled is not None
    assert settled.status == TaskStatus.FAILED
    assert len(attempts) == 1, f"a timed-out step was attempted {len(attempts)} times"


async def test_a_transient_error_is_still_retried(store: TaskStore) -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            msg = "connection refused"
            raise ConnectionError(msg)
        return "done"

    runner = TaskRunner(store, registry_with(flaky, timeout=10))
    runner.STEP_RETRY_BACKOFF = 0.01
    task = one_step_task(store)

    await runner.submit(task)
    settled = await runner.wait(task.id, timeout=20)

    assert settled is not None
    assert settled.status == TaskStatus.COMPLETED
    assert attempts == 3


async def test_a_cancelled_task_is_reopened_only_on_purpose(store: TaskStore) -> None:
    task = one_step_task(store)
    await store.save_task(task)
    await store.update_status(task.id, TaskStatus.CANCELLED, error="operator cancelled")

    task.status = TaskStatus.PENDING
    task.error = None
    await store.save_task(task)
    stuck = await store.load_task(task.id)
    assert stuck is not None
    assert stuck.status == TaskStatus.CANCELLED, "a routine write cleared a cancellation"

    await store.reopen(task.id)
    reopened = await store.load_task(task.id)
    assert reopened is not None
    assert reopened.status == TaskStatus.PENDING
    assert reopened.error is None


async def test_wait_reports_a_task_that_is_not_there(store: TaskStore) -> None:
    runner = TaskRunner(store, registry_with(lambda: "x"))
    assert await runner.wait("missing", timeout=1) is None
