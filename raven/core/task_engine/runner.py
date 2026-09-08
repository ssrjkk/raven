from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from raven.core.metrics import metrics
from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "connection",
    "refused",
    "temporarily",
    "try again",
    "rate limit",
    "quota",
    "429",
    "unavailable",
    "busy",
    "locked",
    "reset by peer",
    "eof",
)


def _is_tool_error(result: Any) -> bool:
    return isinstance(result, str) and result.startswith("[error]")


def _is_transient_error(error: str) -> bool:
    low = error.lower()
    return any(marker in low for marker in _TRANSIENT_MARKERS)


class TaskRunner:
    MAX_CONCURRENT = 10
    SUBMIT_TIMEOUT = 60.0
    MAX_STEP_RETRIES = 2
    STEP_RETRY_BACKOFF = 1.0

    def __init__(self, store: TaskStore, tools: ToolRegistry, max_concurrent: int | None = None):
        self._store = store
        self._tools = tools
        self.MAX_CONCURRENT = max_concurrent or self.MAX_CONCURRENT
        self._sem = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._running: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._pause_events: dict[str, asyncio.Event] = {}

    async def submit(self, task: Task) -> Task:
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self.SUBMIT_TIMEOUT)
        except TimeoutError:
            raise RuntimeError(
                f"No capacity for task '{task.id}' after {self.SUBMIT_TIMEOUT}s "
                f"({len(self._running)}/{self.MAX_CONCURRENT} running). "
                "Wait for a running task to complete."
            ) from None
        try:
            task.status = TaskStatus.PENDING
            task.updated_at = time.time()
            for step in task.steps:
                step.task_id = task.id
            await self._store.save_task(task)

            cancel_ev = asyncio.Event()
            self._cancel_events[task.id] = cancel_ev
            self._pause_events[task.id] = asyncio.Event()

            runner_task = asyncio.create_task(self._execute(task.id, cancel_ev))
            self._running[task.id] = runner_task
            runner_task.add_done_callback(lambda _: self._cleanup(task.id))
            return task
        except Exception:
            self._sem.release()
            raise

    async def cancel(self, task_id: str) -> bool:
        cancel_ev = self._cancel_events.get(task_id)
        if cancel_ev:
            cancel_ev.set()
            await self._store.update_status(task_id, TaskStatus.CANCELLED)
            return True
        task = await self._store.load_task(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            await self._store.update_status(task_id, TaskStatus.CANCELLED)
            return True
        return False

    async def pause(self, task_id: str) -> bool:
        task = await self._store.load_task(task_id)
        if task and task.status == TaskStatus.RUNNING:
            await self._store.update_status(task_id, TaskStatus.PAUSED)
            ev = self._pause_events.get(task_id)
            if ev:
                ev.set()
            return True
        return False

    async def resume(self, task_id: str) -> bool:
        task = await self._store.load_task(task_id)
        if task and task.status == TaskStatus.PAUSED:
            await self._store.update_status(task_id, TaskStatus.RUNNING)
            ev = self._pause_events.get(task_id)
            if ev:
                ev.clear()
            return True
        return False

    async def wait(self, task_id: str, timeout: float | None = None) -> Task:
        runner = self._running.get(task_id)
        if runner:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(runner), timeout=timeout)
        task = await self._store.load_task(task_id)
        return task or Task(goal="")

    async def get_task(self, task_id: str) -> Task | None:
        return await self._store.load_task(task_id)

    async def reset_inflight_steps(self, task: Task) -> None:
        """Reset any RUNNING step of ``task`` back to PENDING.

        Called before resubmitting a task recovered after a restart so the
        persisted steps never show an in-flight (RUNNING) step under a task
        that is no longer executing (PENDING/COMPLETED). Persists each reset.
        """
        for step in task.steps:
            if step.status == TaskStatus.RUNNING:
                step.status = TaskStatus.PENDING
                step.error = None
                step.started_at = None
                step.completed_at = None
                await self._store.update_step(step)

    async def reconcile(self, resume: bool = False) -> list[str]:
        """Reconcile tasks stuck in RUNNING after a process restart.

        A RUNNING status only makes sense while a live runner task exists in
        this process; after a restart there are none, so those statuses are
        stale. With ``resume=False`` they are marked FAILED; with ``resume=True``
        they are requeued to PENDING (and their in-flight steps reset) so a
        caller can re-submit and continue from the last persisted step index.
        Returns the ids of the tasks that were reconciled.
        """
        processed: list[str] = []
        for task in await self._store.list_tasks(status=TaskStatus.RUNNING.value, limit=500):
            if task.id in self._running:
                continue
            # list_tasks returns shell tasks without their steps; reload the full
            # task so the STEP rows are present before deciding how to reconcile.
            full = await self._store.load_task(task.id)
            if full is None:
                continue
            if resume:
                await self.reset_inflight_steps(full)
                await self._store.update_status(task.id, TaskStatus.PENDING)
                logger.info("Task {} requeued after restart (was RUNNING)", task.id)
            else:
                await self._store.update_status(
                    task.id, TaskStatus.FAILED, error="Task interrupted by process restart"
                )
                logger.warning("Task {} marked FAILED: interrupted by restart", task.id)
            processed.append(task.id)
        if processed:
            logger.warning("Reconciled {} stale task(s) after restart", len(processed))
        return processed

    async def _call_tool_with_retries(
        self, task_id: str, step: TaskStep, spec: ToolSpec, cancel_ev: asyncio.Event
    ) -> tuple[Any, str | None]:
        """Execute one tool step with bounded retries for transient failures.

        Returns ``(result, None)`` when the call succeeded or ``(None, error)``
        once retries are exhausted. Error strings coming back from
        :class:`ToolRegistry` (``[error] ...``) are treated as failures, not
        successful results. Transient errors (timeouts, network, rate limits)
        are retried with exponential backoff; permanent errors fail fast.
        """
        timeout = float(spec.timeout)
        attempt = 0
        while True:
            attempt += 1
            error: str | None = None
            result: Any = None
            try:
                result = await asyncio.wait_for(self._tools.call(step.tool, **step.params), timeout=timeout)
                if _is_tool_error(result):
                    error = str(result)
                else:
                    return result, None
            except TimeoutError:
                error = f"Timeout ({timeout}s)"
            except Exception as exc:
                error = str(exc)
                if not _is_transient_error(error):
                    return None, error

            if attempt > self.MAX_STEP_RETRIES or not _is_transient_error(error):
                return None, error

            delay = self.STEP_RETRY_BACKOFF * (2 ** (attempt - 1))
            logger.warning(
                "Task {} step {} ({}) failed (attempt {}/{}): {} — retrying in {}s",
                task_id,
                step.order + 1,
                step.tool,
                attempt,
                self.MAX_STEP_RETRIES + 1,
                error,
                delay,
            )
            if cancel_ev.is_set():
                return None, error
            await asyncio.sleep(delay)

    async def list_tasks(self, user_id: str | None = None, limit: int = 20) -> list[Task]:
        return await self._store.list_tasks(user_id=user_id, limit=limit)

    async def _execute(self, task_id: str, cancel_ev: asyncio.Event) -> None:
        task = await self._store.load_task(task_id)
        if not task:
            logger.error("Task {} not found for execution", task_id)
            return

        task.status = TaskStatus.RUNNING
        task.updated_at = time.time()
        started_at = time.time()
        pause_ev = self._pause_events.get(task_id) or asyncio.Event()
        try:
            await self._store.save_task(task)
        except Exception as e:
            logger.error("Task {} failed to persist RUNNING state: {}", task_id, e)
            task.status = TaskStatus.FAILED
            task.error = f"Internal error: {e}"
            task.updated_at = time.time()
            self._record_outcome(task, started_at)
            try:
                await self._store.save_task(task)
            except Exception as save_exc:
                logger.error("Failed to persist task {} failure: {}", task_id, save_exc)
            return

        try:
            for i in range(task.current_step_index, len(task.steps)):
                if cancel_ev.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.updated_at = time.time()
                    await self._store.save_task(task)
                    self._record_outcome(task, started_at)
                    logger.info("Task {} cancelled at step {}", task_id, i)
                    return

                while pause_ev.is_set():
                    if cancel_ev.is_set():
                        task.status = TaskStatus.CANCELLED
                        task.updated_at = time.time()
                        await self._store.save_task(task)
                        self._record_outcome(task, started_at)
                        logger.info("Task {} cancelled while paused at step {}", task_id, i)
                        return
                    await asyncio.sleep(0.5)

                step = task.steps[i]
                step.status = TaskStatus.RUNNING
                step.started_at = time.time()
                await self._store.update_step(step)
                logger.info("Task {} step {}/{}: {}", task_id, i + 1, len(task.steps), step.description)

                try:
                    spec = self._tools.get(step.tool)
                    if spec is None:
                        msg = f"Unknown tool: {step.tool}"
                        raise ValueError(msg)

                    result, step_error = await self._call_tool_with_retries(task_id, step, spec, cancel_ev)
                    if step_error is not None:
                        step.status = TaskStatus.FAILED
                        step.error = step_error
                        step.completed_at = time.time()
                        task.status = TaskStatus.FAILED
                        task.error = f"Step {i + 1} failed ({step.tool}): {step_error}"
                        task.updated_at = time.time()
                        await self._store.update_step(step)
                        await self._store.save_task(task)
                        self._record_outcome(task, started_at)
                        logger.error("Task {} step {} failed: {}", task_id, i + 1, step_error)
                        return

                    step.status = TaskStatus.COMPLETED
                    step.result = result
                    step.completed_at = time.time()
                    task.current_step_index = i + 1
                    task.updated_at = time.time()
                    await self._store.update_step(step)

                    logger.info("Task {} step {} completed", task_id, i + 1)

                except Exception as e:
                    step.status = TaskStatus.FAILED
                    step.error = str(e)
                    step.completed_at = time.time()
                    task.status = TaskStatus.FAILED
                    task.error = f"Step {i + 1} failed ({step.tool}): {e}"
                    task.updated_at = time.time()
                    await self._store.update_step(step)
                    await self._store.save_task(task)
                    self._record_outcome(task, started_at)
                    logger.error("Task {} step {} failed: {}", task_id, i + 1, e)
                    return

            task.status = TaskStatus.COMPLETED
            task.current_step_index = len(task.steps)
            task.updated_at = time.time()
            await self._store.save_task(task)
            self._record_outcome(task, started_at)
            logger.info("Task {} completed with {} steps", task_id, len(task.steps))

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.updated_at = time.time()
            await self._store.save_task(task)
            self._record_outcome(task, started_at)
            raise
        except Exception as e:
            logger.error("Task {} crashed unexpectedly: {}", task_id, e)
            task.status = TaskStatus.FAILED
            task.error = f"Internal error: {e}"
            task.updated_at = time.time()
            self._record_outcome(task, started_at)
            try:
                await self._store.save_task(task)
            except Exception as save_exc:
                logger.error("Failed to persist task {} failure: {}", task_id, save_exc)

    def on_complete(self, task_id: str, callback: Callable[[], None]) -> None:
        task = self._running.get(task_id)
        if task is not None:
            task.add_done_callback(lambda _: callback())

    def _cleanup(self, task_id: str) -> None:
        self._running.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        self._pause_events.pop(task_id, None)
        self._sem.release()

    def _record_outcome(self, task: Task, started_at: float) -> None:
        status = task.status
        if status == TaskStatus.COMPLETED:
            metrics.inc("task_completed")
        elif status == TaskStatus.FAILED:
            metrics.inc("task_failed")
        elif status == TaskStatus.CANCELLED:
            metrics.inc("task_cancelled")
        else:
            return
        metrics.observe("task_duration", time.time() - started_at)

    async def shutdown(self) -> None:
        pending = list(self._running.values())
        self._running.clear()
        self._cancel_events.clear()
        self._pause_events.clear()
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
