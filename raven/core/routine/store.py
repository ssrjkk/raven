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
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    schedule TEXT NOT NULL DEFAULT '0 7 * * *',
    action TEXT NOT NULL DEFAULT 'send_briefing',
    config TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    last_run_at REAL,
    last_run_status TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_logs (
    id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT '',
    message TEXT DEFAULT '',
    duration_ms REAL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routines_user ON routines(user_id);
CREATE INDEX IF NOT EXISTS idx_routines_status ON routines(status);
CREATE INDEX IF NOT EXISTS idx_routine_logs_rid ON routine_logs(routine_id);
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

    def save_routine(self, routine: Routine) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO routines
               (id, user_id, channel, name, description, trigger, schedule,
                action, config, status, last_run_at, last_run_status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                routine.id, routine.user_id, routine.channel,
                routine.name, routine.description, routine.trigger.value,
                routine.schedule, routine.action.value,
                json.dumps(routine.config, default=str),
                routine.status.value, routine.last_run_at,
                routine.last_run_status, routine.created_at, routine.updated_at,
            ),
        )
        conn.commit()

    def load_routine(self, routine_id: str) -> Routine | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        if not row:
            return None
        return self._row_to_routine(row)

    def list_routines(self, user_id: str | None = None) -> list[Routine]:
        conn = self._conn()
        where = "1=1"
        params: list[Any] = []
        if user_id:
            where = "user_id = ?"
            params.append(user_id)
        rows = conn.execute(
            f"SELECT * FROM routines WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_routine(r) for r in rows]

    def list_active(self) -> list[Routine]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM routines WHERE status = 'active'").fetchall()
        return [self._row_to_routine(r) for r in rows]

    def update_status(self, routine_id: str, status: RoutineStatus) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE routines SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, time.time(), routine_id),
        )
        conn.commit()

    def update_last_run(self, routine_id: str, status: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE routines SET last_run_at = ?, last_run_status = ?, updated_at = ? WHERE id = ?",
            (time.time(), status, time.time(), routine_id),
        )
        conn.commit()

    def delete_routine(self, routine_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM routine_logs WHERE routine_id = ?", (routine_id,))
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.commit()

    def save_log(self, log: RoutineLog) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO routine_logs (id, routine_id, status, message, duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (log.id, log.routine_id, log.status, log.message, log.duration_ms, log.created_at),
        )
        conn.commit()

    def get_logs(self, routine_id: str, limit: int = 50) -> list[RoutineLog]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM routine_logs WHERE routine_id = ? ORDER BY created_at DESC LIMIT ?",
            (routine_id, limit),
        ).fetchall()
        return [RoutineLog(**dict(r)) for r in rows]

    def _row_to_routine(self, row: sqlite3.Row) -> Routine:
        return Routine(
            id=row["id"],
            user_id=row["user_id"] or "",
            channel=row["channel"] or "",
            name=row["name"],
            description=row["description"] or "",
            trigger=RoutineTrigger(row["trigger"]),
            schedule=row["schedule"],
            action=RoutineAction(row["action"]),
            config=json.loads(row["config"]) if row["config"] else {},
            status=RoutineStatus(row["status"]),
            last_run_at=row["last_run_at"],
            last_run_status=row["last_run_status"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
