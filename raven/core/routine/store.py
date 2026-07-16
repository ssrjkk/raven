from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

from raven.core._json import json
from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger
from raven.core.store import BaseStore
from raven.utils.performance import measure_latency

SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    action TEXT NOT NULL,
    trigger TEXT NOT NULL,
    schedule TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    last_run_status TEXT,
    last_run_at REAL,
    config TEXT DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_logs (
    id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    duration_ms REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routine_status ON routines(status);
CREATE INDEX IF NOT EXISTS idx_routine_user_id ON routines(user_id);
CREATE INDEX IF NOT EXISTS idx_routine_logs_routine_id ON routine_logs(routine_id);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""


class RoutineStore(BaseStore):
    SCHEMA = SCHEMA

    def __init__(self, db_path: str | Path):
        super().__init__(db_path)

    @measure_latency()
    async def save_routine(self, routine: Routine) -> None:
        config_json = json.dumps(routine.config)
        await self._execute(
            """INSERT OR REPLACE INTO routines
               (id, name, action, trigger, schedule, status,
                user_id, channel, last_run_status, last_run_at, config, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                routine.id,
                routine.name,
                routine.action.value,
                routine.trigger.value,
                routine.schedule,
                routine.status.value,
                routine.user_id,
                routine.channel,
                routine.last_run_status,
                routine.last_run_at,
                config_json,
                routine.created_at or time.time(),
            ),
        )
        await self._commit()

    @measure_latency()
    async def load_routine(self, routine_id: str) -> Routine | None:
        row = await self._fetchone("SELECT * FROM routines WHERE id = ?", (routine_id,))
        if not row:
            return None
        return self._row_to_routine(row)

    @measure_latency()
    async def delete_routine(self, routine_id: str) -> None:
        await self._execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        await self._execute("DELETE FROM routine_logs WHERE routine_id = ?", (routine_id,))
        await self._commit()

    @measure_latency()
    async def list_routines(
        self, user_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Routine]:
        parts = ["SELECT * FROM routines WHERE 1=1"]
        params: list[Any] = []
        if user_id:
            parts.append("AND user_id = ?")
            params.append(user_id)
        if status:
            parts.append("AND status = ?")
            params.append(status)
        parts.append("ORDER BY created_at DESC LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        rows = await self._fetchall(" ".join(parts), params)
        return [self._row_to_routine(r) for r in rows]

    @measure_latency()
    async def count_routines(self, user_id: str | None = None, status: str | None = None) -> int:
        parts = ["SELECT COUNT(*) as cnt FROM routines WHERE 1=1"]
        params: list[Any] = []
        if user_id:
            parts.append("AND user_id = ?")
            params.append(user_id)
        if status:
            parts.append("AND status = ?")
            params.append(status)
        row = await self._fetchone(" ".join(parts), params)
        return row["cnt"] if row else 0

    async def list_active(self) -> list[Routine]:
        return await self.list_routines(status="active")

    @measure_latency()
    async def update_status(self, routine_id: str, status: RoutineStatus) -> None:
        await self._execute("UPDATE routines SET status = ? WHERE id = ?", (status.value, routine_id))
        await self._commit()

    @measure_latency()
    async def update_last_run(self, routine_id: str, status: str) -> None:
        await self._execute(
            "UPDATE routines SET last_run_status = ?, last_run_at = ? WHERE id = ?",
            (status, time.time(), routine_id),
        )
        await self._commit()

    @measure_latency()
    async def save_log(self, log: RoutineLog) -> None:
        await self._execute(
            """INSERT OR REPLACE INTO routine_logs
               (id, routine_id, status, message, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (log.id, log.routine_id, log.status, log.message, log.duration_ms, log.created_at or time.time()),
        )
        await self._commit()

    @measure_latency()
    async def get_logs(self, routine_id: str, limit: int = 20) -> list[RoutineLog]:
        rows = await self._fetchall(
            "SELECT * FROM routine_logs WHERE routine_id = ? ORDER BY created_at DESC LIMIT ?",
            (routine_id, limit),
        )
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

    def _row_to_routine(self, row: aiosqlite.Row) -> Routine:
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
