from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    action TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    schedule TEXT NOT NULL DEFAULT '08:00',
    status TEXT NOT NULL DEFAULT 'active',
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    last_run_status TEXT,
    last_run_at REAL,
    config TEXT NOT NULL DEFAULT '{}',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS routine_logs (
    id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    duration_ms REAL,
    created_at REAL NOT NULL
);
"""


class RoutineStore:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        conn = sqlite3.connect(self._path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._path)

    def save_routine(self, routine: Routine):
        conn = self._conn()
        config_json = json.dumps(routine.config)
        conn.execute(
            """INSERT OR REPLACE INTO routines
               (id, name, action, trigger, schedule, status,
                user_id, channel, last_run_status, last_run_at, config, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                routine.id, routine.name, routine.action.value,
                routine.trigger.value, routine.schedule, routine.status.value,
                routine.user_id, routine.channel, routine.last_run_status,
                routine.last_run_at, config_json, routine.created_at or time.time(),
            ),
        )
        conn.commit()

    def load_routine(self, routine_id: str) -> Routine | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM routines WHERE id = ?", (routine_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_routine(row)

    def delete_routine(self, routine_id: str):
        conn = self._conn()
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.execute("DELETE FROM routine_logs WHERE routine_id = ?", (routine_id,))
        conn.commit()

    def list_routines(self, user_id: str | None = None, status: str | None = None) -> list[Routine]:
        conn = self._conn()
        parts = ["SELECT * FROM routines WHERE 1=1"]
        params: list[Any] = []
        if user_id:
            parts.append("AND user_id = ?")
            params.append(user_id)
        if status:
            parts.append("AND status = ?")
            params.append(status)
        parts.append("ORDER BY created_at DESC")
        rows = conn.execute(" ".join(parts), params).fetchall()
        return [self._row_to_routine(r) for r in rows]

    def list_active(self) -> list[Routine]:
        return self.list_routines(status="active")

    def update_status(self, routine_id: str, status: RoutineStatus):
        conn = self._conn()
        conn.execute(
            "UPDATE routines SET status = ? WHERE id = ?",
            (status.value, routine_id),
        )
        conn.commit()

    def update_last_run(self, routine_id: str, status: str):
        conn = self._conn()
        conn.execute(
            "UPDATE routines SET last_run_status = ?, last_run_at = ? WHERE id = ?",
            (status, time.time(), routine_id),
        )
        conn.commit()

    def save_log(self, log: RoutineLog):
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO routine_logs
               (id, routine_id, status, message, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (log.id, log.routine_id, log.status, log.message, log.duration_ms, log.created_at or time.time()),
        )
        conn.commit()

    def get_logs(self, routine_id: str, limit: int = 20) -> list[RoutineLog]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM routine_logs WHERE routine_id = ? ORDER BY created_at DESC LIMIT ?",
            (routine_id, limit),
        ).fetchall()
        return [
            RoutineLog(
                id=r["id"],
                routine_id=r["routine_id"],
                status=r["status"],
                message=r["message"] or "",
                duration_ms=r["duration_ms"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def _row_to_routine(self, row: sqlite3.Row) -> Routine:
        config = json.loads(row["config"]) if row["config"] else {}
        return Routine(
            id=row["id"],
            name=row["name"],
            action=RoutineAction(row["action"]),
            trigger=RoutineTrigger(row["trigger"]),
            schedule=row["schedule"],
            status=RoutineStatus(row["status"]),
            user_id=row["user_id"],
            channel=row["channel"],
            last_run_status=row["last_run_status"],
            last_run_at=row["last_run_at"],
            config=config,
            created_at=row["created_at"],
        )
