from __future__ import annotations

import asyncio
import contextlib
import time

from loguru import logger

from raven.core.task_engine.models import Task, TaskStatus
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry


class TaskRunner:
    MAX_CONCURRENT = 10

    def __init__(self, store: TaskStore, tools: ToolRegistry):
        self._store = store
        self._tools = tools
        self._running: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    async def submit(self, task: Task) -> Task:
        if len(self._running) >= self.MAX_CONCURRENT:
            raise RuntimeError(
                f"Too many concurrent tasks ({len(self._running)}/{self.MAX_CONCURRENT}). "
                "Wait for a running task to complete."
            )
        task.status = TaskStatus.PENDING
        task.updated_at = time.time()
        for step in task.steps:
            step.task_id = task.id
        self._store.save_task(task)

        cancel_ev = asyncio.Event()
        self._cancel_events[task.id] = cancel_ev

        runner_task = asyncio.create_task(self._execute(task.id, cancel_ev))
        self._running[task.id] = runner_task
        runner_task.add_done_callback(lambda _: self._cleanup(task.id))
        return task

    async def cancel(self, task_id: str) -> bool:
        cancel_ev = self._cancel_events.get(task_id)
        if cancel_ev:
            cancel_ev.set()
            self._store.update_status(task_id, TaskStatus.CANCELLED)
            return True
        task = self._store.load_task(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            self._store.update_status(task_id, TaskStatus.CANCELLED)
            return True
        return False

    async def pause(self, task_id: str) -> bool:
        task = self._store.load_task(task_id)
        if task and task.status == TaskStatus.RUNNING:
            self._store.update_status(task_id, TaskStatus.PAUSED)
            return True
        return False

    async def wait(self, task_id: str, timeout: float | None = None) -> Task:
        runner = self._running.get(task_id)
        if runner:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(runner, timeout=timeout)
        return self._store.load_task(task_id) or Task(goal="")

    def get_task(self, task_id: str) -> Task | None:
        return self._store.load_task(task_id)

    def list_tasks(self, user_id: str | None = None, limit: int = 20) -> list[Task]:
        return self._store.list_tasks(user_id=user_id, limit=limit)

    async def _execute(self, task_id: str, cancel_ev: asyncio.Event) -> None:
        task = self._store.load_task(task_id)
        if not task:
            logger.error("Task {} not found for execution", task_id)
            return

        task.status = TaskStatus.RUNNING
        task.updated_at = time.time()
        self._store.save_task(task)

        try:
            for i in range(task.current_step_index, len(task.steps)):
                if cancel_ev.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.updated_at = time.time()
                    self._store.save_task(task)
                    logger.info("Task {} cancelled at step {}", task_id, i)
                    return

                step = task.steps[i]
                step.status = TaskStatus.RUNNING
                step.started_at = time.time()
                self._store.save_task(task)
                logger.info("Task {} step {}/{}: {}", task_id, i + 1, len(task.steps), step.description)

                try:
                    spec = self._tools.get(step.tool)
                    if spec is None:
                        raise ValueError(f"Unknown tool: {step.tool}")

                    timeout = spec.timeout

                    result = await asyncio.wait_for(
                        self._tools.call(step.tool, **step.params),
                        timeout=timeout,
                    )

                    step.status = TaskStatus.COMPLETED
                    step.result = result
                    step.completed_at = time.time()
                    task.current_step_index = i + 1
                    task.updated_at = time.time()
                    self._store.save_task(task)

                    logger.info("Task {} step {} completed", task_id, i + 1)

                except TimeoutError:
                    step.status = TaskStatus.FAILED
                    step.error = f"Timeout ({spec.timeout}s)" if spec else "Timeout"
                    step.completed_at = time.time()
                    task.status = TaskStatus.FAILED
                    task.error = f"Step {i + 1} timed out: {step.description}"
                    task.updated_at = time.time()
                    self._store.save_task(task)
                    logger.warning("Task {} step {} timed out", task_id, i + 1)
                    return

                except Exception as e:
                    step.status = TaskStatus.FAILED
                    step.error = str(e)
                    step.completed_at = time.time()
                    task.status = TaskStatus.FAILED
                    task.error = f"Step {i + 1} failed ({step.tool}): {e}"
                    task.updated_at = time.time()
                    self._store.save_task(task)
                    logger.error("Task {} step {} failed: {}", task_id, i + 1, e)
                    return

            task.status = TaskStatus.COMPLETED
            task.current_step_index = len(task.steps)
            task.updated_at = time.time()
            self._store.save_task(task)
            logger.info("Task {} completed with {} steps", task_id, len(task.steps))

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.updated_at = time.time()
            self._store.save_task(task)
            raise

    def _cleanup(self, task_id: str) -> None:
        self._running.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
