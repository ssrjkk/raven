from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from raven.core.llm import LLMRouter
from raven.core.mcp.mcp_client import MCPClientPool
from raven.core.task_engine.models import Task
from raven.core.task_engine.planner import TaskPlanner
from raven.core.task_engine.runner import TaskRunner
from raven.core.task_engine.store import TaskStore
from raven.tools.register_all import create_tool_registry


class TaskOrchestrator:
    def __init__(
        self,
        db: Any,
        llm: LLMRouter,
        mcp_pool: MCPClientPool,
        send_notification: Callable[[str, str, str], Awaitable[None]] | None = None,
    ):
        self._db = db
        self._llm = llm
        self._mcp_pool = mcp_pool
        self._send_notification = send_notification
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._store: TaskStore | None = None
        self._planner: TaskPlanner | None = None
        self._runner: TaskRunner | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._store = TaskStore(self._db.db_path)
        tools = create_tool_registry(self._mcp_pool)
        self._planner = TaskPlanner(tools)
        self._runner = TaskRunner(self._store, tools)
        running = await self._store.list_tasks(limit=100)
        async with self._lock:
            for t in running:
                if t.status.value in ("pending", "running"):
                    self._tasks[t.id] = t
        logger.info("TaskOrchestrator started, {} active tasks", len(self._tasks))

    async def stop(self) -> None:
        async with self._lock:
            self._tasks.clear()
        logger.info("TaskOrchestrator stopped")

    async def create_and_run(
        self,
        goal: str,
        user_id: str,
        channel: str,
        session_id: str = "",
    ) -> Task:
        if self._planner is None or self._runner is None:
            raise RuntimeError("TaskOrchestrator not started")

        task = await self._planner.plan(
            goal,
            self._llm,
            user_id=user_id,
            channel=channel,
        )
        async with self._lock:
            self._tasks[task.id] = task

        plan_text = task.plan_summary or goal
        steps_text = "\n".join(f"  {i + 1}. {s.description}" for i, s in enumerate(task.steps[:10]))
        await self._notify(channel, session_id, f"📋 Plan: {plan_text}\n{steps_text}")

        await self._runner.submit(task)
        bg_task = asyncio.create_task(self._wait_and_notify(task, channel, session_id))
        self._bg_tasks.add(bg_task)
        bg_task.add_done_callback(self._bg_tasks.discard)
        return task

    async def _wait_and_notify(self, task: Task, channel: str, session_id: str) -> None:
        if self._runner is None:
            raise RuntimeError("TaskOrchestrator not started")
        try:
            task = await self._runner.wait(task.id, timeout=600)
            async with self._lock:
                self._tasks[task.id] = task
            msg = self._format_result(task)
        except Exception as e:
            logger.error("Task {} execution error: {}", task.id, e)
            msg = f"❌ Task error: {e}"
        await self._notify(channel, session_id, msg)

    def _format_result(self, task: Task) -> str:
        if task.status.value == "completed":
            results = []
            for s in task.steps:
                if s.result:
                    r = str(s.result)[:200]
                    results.append(f"  ✅ {s.description}: {r}")
            return "✅ Task completed!\n" + "\n".join(results[:10])
        if task.status.value == "failed":
            return f"❌ Task failed: {task.error or 'Unknown error'}"
        if task.status.value == "cancelled":
            return "🚫 Task cancelled"
        return f"Task status: {task.status.value}"

    async def _notify(self, channel: str, session_id: str, text: str) -> None:
        if self._send_notification:
            await self._send_notification(channel, session_id, text)

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def list_tasks(self) -> list[Task]:
        async with self._lock:
            return list(self._tasks.values())
