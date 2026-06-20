from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from raven.core.task_engine.models import Task, TaskPriority, TaskStatus, TaskStep

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn  # type: ignore[no-any-return]


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL,
    plan_summary TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 1,
    current_step_index INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    scheduled_at REAL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    params TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    error TEXT,
    started_at REAL,
    completed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id);
CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status);
"""


class TaskStore:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        conn = sqlite3.connect(self._path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._path)

    def save_task(self, task: Task) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, user_id, channel, goal, plan_summary, status, priority,
                current_step_index, result, error, created_at, updated_at,
                scheduled_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.user_id,
                task.channel,
                task.goal,
                task.plan_summary,
                task.status.value,
                task.priority.value,
                task.current_step_index,
                task.result,
                task.error,
                task.created_at,
                task.updated_at,
                task.scheduled_at,
                json.dumps(task.metadata, default=str),
            ),
        )
        for step in task.steps:
            conn.execute(
                """INSERT OR REPLACE INTO task_steps
                   (id, task_id, step_order, description, tool, params,
                    status, result, error, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    step.id,
                    step.task_id,
                    step.order,
                    step.description,
                    step.tool,
                    json.dumps(step.params, default=str),
                    step.status.value,
                    json.dumps(step.result, default=str) if step.result is not None else None,
                    step.error,
                    step.started_at,
                    step.completed_at,
                ),
            )
        conn.commit()

    def load_task(self, task_id: str) -> Task | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = self._row_to_task(row)
        step_rows = conn.execute(
            "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_order",
            (task_id,),
        ).fetchall()
        task.steps = [self._row_to_step(r) for r in step_rows]
        return task

    def list_tasks(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        conn = self._conn()
        where = []
        params: list[Any] = []
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if status:
            where.append("status = ?")
            params.append(status)
        clause = " AND ".join(where) if where else "1=1"
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608
            (*params, limit, offset),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_status(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, error = ? WHERE id = ?",
            (status.value, time.time(), error, task_id),
        )
        conn.commit()

    def update_step(self, step: TaskStep) -> None:
        conn = self._conn()
        conn.execute(
            """UPDATE task_steps SET status = ?, result = ?, error = ?,
               started_at = ?, completed_at = ? WHERE id = ?""",
            (
                step.status.value,
                json.dumps(step.result, default=str) if step.result is not None else None,
                step.error,
                step.started_at,
                step.completed_at,
                step.id,
            ),
        )
        conn.commit()

    def delete_task(self, task_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM task_steps WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

    def count_tasks(self, user_id: str | None = None, status: str | None = None) -> int:
        conn = self._conn()
        where = []
        params: list[Any] = []
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if status:
            where.append("status = ?")
            params.append(status)
        clause = " AND ".join(where) if where else "1=1"
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE {clause}", params).fetchone()  # noqa: S608
        return row["cnt"] if row else 0

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            user_id=row["user_id"],
            channel=row["channel"] or "",
            goal=row["goal"],
            plan_summary=row["plan_summary"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            current_step_index=row["current_step_index"],
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            scheduled_at=row["scheduled_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            steps=[],
        )

    def _row_to_step(self, row: sqlite3.Row) -> TaskStep:
        return TaskStep(
            id=row["id"],
            task_id=row["task_id"],
            order=row["step_order"],
            description=row["description"] or "",
            tool=row["tool"] or "",
            params=json.loads(row["params"]) if row["params"] else {},
            status=TaskStatus(row["status"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
