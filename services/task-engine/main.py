from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

from services.observability_sdk.idempotency import IdempotencyStore
from services.observability_sdk.outbox import OutboxStore

try:
    from opentelemetry_setup import setup_opentelemetry
except ImportError:
    def setup_opentelemetry(app=None, service_name=None): pass

app = FastAPI(title="Task Engine", version="1.0.0")
setup_opentelemetry(app, service_name="task-engine")
started_at = 0.0
outbox: OutboxStore | None = None
idempotency: IdempotencyStore | None = None
db_conn: sqlite3.Connection | None = None


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


_app_tasks: dict[str, Task] = {}


def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            input TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            finished_at REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.commit()
    return conn


def _cleanup_old_tasks(conn: sqlite3.Connection, ttl_hours: int = 168) -> None:
    cutoff = time.time() - ttl_hours * 3600
    cursor = conn.execute("DELETE FROM tasks WHERE created_at < ? AND status IN ('completed', 'failed')", (cutoff,))
    if cursor.rowcount:
        logger.info("cleaned {} old tasks", cursor.rowcount)
    conn.commit()


def _load_tasks(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 1000").fetchall()
    for row in rows:
        _app_tasks[row["id"]] = Task(
            id=row["id"],
            type=row["type"],
            input=row["input"],
            status=TaskStatus(row["status"]),
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )
    logger.info("loaded {} tasks from DB", len(_app_tasks))


def _save_task(task: Task) -> None:
    if db_conn is None:
        _app_tasks[task.id] = task
        return
    db_conn.execute(
        """INSERT OR REPLACE INTO tasks (id, type, input, status, result, error, created_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (task.id, task.type, task.input, task.status.value, task.result, task.error, task.created_at, task.finished_at),
    )
    db_conn.commit()


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(3600)
        if db_conn:
            _cleanup_old_tasks(db_conn)


@app.on_event("startup")
async def startup():
    global started_at, outbox, idempotency, db_conn
    started_at = time.time()
    db_path = os.environ.get("DB_PATH", "/data/task.db")
    try:
        db_conn = _init_db(db_path)
        _load_tasks(db_conn)
        _cleanup_old_tasks(db_conn)
        outbox = OutboxStore(db_path=db_path.replace(".db", "_outbox.db"), service_name="task-engine")
        idempotency = IdempotencyStore(db_path=db_path.replace(".db", "_idem.db"))
        logger.info("task-engine started, DB={}", db_path)
        asyncio.create_task(_periodic_cleanup())
    except Exception as e:
        logger.warning("task-engine started without persistence: {}", e)


@app.on_event("shutdown")
async def shutdown():
    if db_conn:
        db_conn.close()
    logger.info("task-engine shutdown")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "task-engine",
        "tasks": len(_app_tasks),
        "uptime": round(time.time() - started_at, 1),
    }


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return {"status": "ready", "persistence": db_conn is not None}


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    counts: dict[str, int] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for t in _app_tasks.values():
        counts[t.status.value] = counts.get(t.status.value, 0) + 1
    return {"tasks": counts, "uptime_seconds": round(time.time() - started_at, 1)}


@app.post("/api/v1/tasks")
async def create_task(request: dict[str, Any]) -> dict[str, Any]:
    task_type = request.get("type", "generic")
    task_input = request.get("input", "")
    idem_key = request.get("idempotency_key")

    if idem_key and idempotency:
        existing = idempotency.get(idem_key)
        if existing:
            logger.info("Task idempotent hit: key={}", idem_key)
            return {"status": "completed", "cached": True, "id": idem_key}

    task = Task(type=task_type, input=task_input, created_at=time.time())
    _save_task(task)
    logger.info("Task created: id={} type={}", task.id, task_type)

    asyncio.create_task(_execute_task(task))

    if idem_key and idempotency:
        idempotency.set(idem_key, 201, json.dumps({"id": task.id}))

    if outbox:
        outbox.enqueue("task.created", {"task_id": task.id, "type": task_type})

    return {"id": task.id, "status": task.status.value, "type": task_type}


async def _execute_task(task: Task):
    task.status = TaskStatus.RUNNING
    _save_task(task)
    try:
        await asyncio.sleep(0.5)
        task.result = f"Executed {task.type}: {task.input[:50]}..."
        task.status = TaskStatus.COMPLETED
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        logger.error("Task failed: id={} error={}", task.id, task.error)
    finally:
        task.finished_at = time.time()
        _save_task(task)

    logger.info("Task completed: id={} status={} duration={:.1f}s", task.id, task.status.value, task.duration)

    if outbox:
        outbox.enqueue("task.completed", {"task_id": task.id, "result": task.result, "status": task.status.value})


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    task = _app_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if db_conn:
        row = db_conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            return dict(row)
    return {
        "id": task.id,
        "type": task.type,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "duration": round(task.duration, 2),
        "created_at": task.created_at,
    }


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8005"))
    uvicorn.run(app, host="0.0.0.0", port=port)
