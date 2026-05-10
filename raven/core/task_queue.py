from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable
from loguru import logger
from raven.core.db import Database


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    def __init__(
        self,
        id: str,
        name: str,
        payload: dict,
        status: TaskStatus = TaskStatus.PENDING,
        created_at: str | None = None,
        result: str | None = None,
        error: str | None = None,
    ):
        self.id = id
        self.name = name
        self.payload = payload
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.result = result
        self.error = error

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "payload": json.dumps(self.payload),
            "status": self.status.value,
            "created_at": self.created_at,
            "result": self.result or "",
            "error": self.error or "",
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"],
            name=d["name"],
            payload=json.loads(d["payload"]) if isinstance(d["payload"], str) else d["payload"],
            status=TaskStatus(d.get("status", "pending")),
            created_at=d.get("created_at"),
            result=d.get("result"),
            error=d.get("error"),
        )


JobHandler = Callable[..., Awaitable[str]]


class TaskQueue:
    def __init__(self, db: Database, max_concurrent: int = 5):
        self.db = db
        self.max_concurrent = max_concurrent
        self._handlers: dict[str, JobHandler] = {}
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False

    def register(self, name: str, handler: JobHandler):
        self._handlers[name] = handler
        logger.info("Registered task handler: {}", name)

    async def enqueue(self, name: str, payload: dict | None = None) -> Task:
        task = Task(
            id=uuid.uuid4().hex,
            name=name,
            payload=payload or {},
        )
        await self.db.save_plugin_state("task_queue", task.id, json.dumps(task.to_dict()))
        await self._queue.put(task)
        logger.info("Enqueued task: {} ({})", task.id, name)
        return task

    async def start(self):
        self._running = True
        for i in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        logger.info("Task queue started with {} workers", self.max_concurrent)

    async def stop(self):
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Task queue stopped")

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            handler = self._handlers.get(task.name)
            if not handler:
                task.status = TaskStatus.FAILED
                task.error = f"No handler for task type: {task.name}"
                await self._persist(task)
                continue

            task.status = TaskStatus.RUNNING
            await self._persist(task)
            logger.info("Worker {} running task: {} ({})", worker_id, task.id, task.name)

            try:
                result = await handler(**task.payload)
                task.status = TaskStatus.DONE
                task.result = str(result)[:5000]
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)[:1000]
                logger.error("Worker {} task {} failed: {}", worker_id, task.id, e)

            await self._persist(task)
            self._queue.task_done()

    async def _persist(self, task: Task):
        await self.db.save_plugin_state("task_queue", task.id, json.dumps(task.to_dict()))

    async def get_task(self, task_id: str) -> Task | None:
        raw = await self.db.get_plugin_state("task_queue", task_id)
        if raw:
            return Task.from_dict(json.loads(raw))
        return None

    async def list_tasks(self, limit: int = 20) -> list[Task]:
        raw = await self.db.get_plugin_state("task_queue", "index")
        task_ids = json.loads(raw) if raw else []
        tasks = []
        for tid in task_ids[-limit:]:
            t = await self.get_task(tid)
            if t:
                tasks.append(t)
        return tasks[::-1]

    async def cancel(self, task_id: str) -> bool:
        task = await self.get_task(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            await self._persist(task)
            return True
        return False
