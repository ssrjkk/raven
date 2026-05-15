from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

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
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    schedule TEXT NOT NULL DEFAULT '08:00',
    status TEXT NOT NULL DEFAULT 'active',
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    last_run_status TEXT,
    config TEXT NOT NULL DEFAULT '{}',
    created_at REAL
);
"""


class RoutineStore:
    def __init__(self, db_path: Path):
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
                user_id, channel, last_run_status, config, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                routine.id, routine.name, routine.action.value,
                routine.trigger.value, routine.schedule, routine.status.value,
                routine.user_id, routine.channel, routine.last_run_status,
                config_json, routine.created_at or time.time(),
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

    def update_status(self, routine_id: str, status: RoutineStatus):
        conn = self._conn()
        conn.execute(
            "UPDATE routines SET status = ? WHERE id = ?",
            (status.value, routine_id),
        )
        conn.commit()

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
            config=config,
            created_at=row["created_at"],
        )
