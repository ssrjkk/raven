from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

import uvicorn
from fastapi import FastAPI
from loguru import logger

from services.observability_sdk.outbox import OutboxStore
from services.observability_sdk.idempotency import IdempotencyStore

app = FastAPI(title="Task Engine", version="1.0.0")
started_at = 0.0
outbox: OutboxStore | None = None
idempotency: IdempotencyStore | None = None


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    input: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        if self.finished_at and self.created_at:
            return self.finished_at - self.created_at
        return 0.0


_tasks: dict[str, Task] = {}


@app.on_event("startup")
async def startup():
    global started_at, outbox, idempotency
    started_at = time.time()
    db_path = os.environ.get("DB_PATH", "/data/task.db")
    outbox = OutboxStore(db_path=db_path.replace(".db", "_outbox.db"), service_name="task-engine")
    idempotency = IdempotencyStore(db_path=db_path.replace(".db", "_idem.db"))
    logger.info("task-engine started")


@app.get("/health")
async def health():
    import time
    return {"status": "healthy", "service": "task-engine", "tasks": len(_tasks), "uptime": round(time.time() - started_at, 1)}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for t in _tasks.values():
        counts[t.status.value] = counts.get(t.status.value, 0) + 1
    return {"tasks": counts}


@app.post("/api/v1/tasks")
async def create_task(request: dict):
    task_type = request.get("type", "generic")
    task_input = request.get("input", "")
    idem_key = request.get("idempotency_key")

    if idem_key and idempotency:
        existing = idempotency.get(idem_key)
        if existing:
            return {"status": "completed", "cached": True, "id": idem_key}

    task = Task(type=task_type, input=task_input, created_at=time.time())
    _tasks[task.id] = task
    logger.info("Task created: id={} type={}", task.id, task_type)

    asyncio.create_task(execute_task(task))

    if idem_key and idempotency:
        import json
        idempotency.set(idem_key, 201, json.dumps({"id": task.id}))

    if outbox:
        outbox.enqueue("task.created", {"task_id": task.id, "type": task_type})

    return {"id": task.id, "status": task.status.value, "type": task_type}


async def execute_task(task: Task):
    task.status = TaskStatus.RUNNING
    await asyncio.sleep(0.5)
    task.status = TaskStatus.COMPLETED
    task.finished_at = time.time()
    task.result = f"Executed {task.type}: {task.input[:50]}..."
    logger.info("Task completed: id={} duration={:.1f}s", task.id, task.duration)

    if outbox:
        outbox.enqueue("task.completed", {"task_id": task.id, "result": task.result})


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        return {"error": "not found"}, 404
    return {
        "id": task.id, "type": task.type, "status": task.status.value,
        "result": task.result, "error": task.error,
        "duration": round(task.duration, 2), "created_at": task.created_at,
    }


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8005"))
    uvicorn.run(app, host="0.0.0.0", port=port)
