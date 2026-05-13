from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from raven.core.monitor.models import Condition, ConditionOperator, Monitor, MonitorCheck, MonitorStatus, MonitorType

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitors (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    status TEXT NOT NULL DEFAULT 'active',
    config TEXT NOT NULL DEFAULT '{}',
    conditions TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_checks (
    id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'unknown',
    response_time_ms REAL,
    result TEXT DEFAULT '{}',
    error TEXT,
    triggered INTEGER NOT NULL DEFAULT 0,
    checked_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_monitors_user ON monitors(user_id);
CREATE INDEX IF NOT EXISTS idx_monitors_status ON monitors(status);
CREATE INDEX IF NOT EXISTS idx_monitor_checks_mid ON monitor_checks(monitor_id);
CREATE INDEX IF NOT EXISTS idx_monitor_checks_time ON monitor_checks(checked_at);
"""


class MonitorStore:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        conn = sqlite3.connect(self._path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._path)

    def save_monitor(self, monitor: Monitor) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO monitors
               (id, user_id, channel, name, type, target, interval_seconds,
                status, config, conditions, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                monitor.id, monitor.user_id, monitor.channel, monitor.name,
                monitor.type.value, monitor.target, monitor.interval_seconds,
                monitor.status.value,
                json.dumps(monitor.config, default=str),
                json.dumps([c.model_dump() for c in monitor.conditions], default=str),
                monitor.created_at, monitor.updated_at,
            ),
        )
        conn.commit()

    def load_monitor(self, monitor_id: str) -> Monitor | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
        if not row:
            return None
        monitor = self._row_to_monitor(row)
        last = conn.execute(
            "SELECT * FROM monitor_checks WHERE monitor_id = ? ORDER BY checked_at DESC LIMIT 1",
            (monitor_id,),
        ).fetchone()
        if last:
            monitor.last_check = self._row_to_check(last)
        return monitor

    def list_monitors(self, user_id: str | None = None, status: str | None = None) -> list[Monitor]:
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
            f"SELECT * FROM monitors WHERE {clause} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_monitor(r) for r in rows]

    def list_active(self) -> list[Monitor]:
        return self.list_monitors(status="active")

    def update_status(self, monitor_id: str, status: MonitorStatus) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE monitors SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, time.time(), monitor_id),
        )
        conn.commit()

    def delete_monitor(self, monitor_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM monitor_checks WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        conn.commit()

    def save_check(self, check: MonitorCheck) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO monitor_checks
               (id, monitor_id, status, response_time_ms, result, error, triggered, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                check.id, check.monitor_id, check.status, check.response_time_ms,
                json.dumps(check.result, default=str), check.error,
                1 if check.triggered else 0, check.checked_at,
            ),
        )
        conn.commit()

    def get_checks(self, monitor_id: str, limit: int = 50) -> list[MonitorCheck]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM monitor_checks WHERE monitor_id = ? ORDER BY checked_at DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
        return [self._row_to_check(r) for r in rows]

    def _row_to_monitor(self, row: sqlite3.Row) -> Monitor:
        conds_data = json.loads(row["conditions"]) if row["conditions"] else []
        conditions = [Condition(**c) for c in conds_data]
        return Monitor(
            id=row["id"],
            user_id=row["user_id"] or "",
            channel=row["channel"] or "",
            name=row["name"],
            type=MonitorType(row["type"]),
            target=row["target"] or "",
            interval_seconds=row["interval_seconds"],
            status=MonitorStatus(row["status"]),
            config=json.loads(row["config"]) if row["config"] else {},
            conditions=conditions,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_check(self, row: sqlite3.Row) -> MonitorCheck:
        return MonitorCheck(
            id=row["id"],
            monitor_id=row["monitor_id"],
            status=row["status"],
            response_time_ms=row["response_time_ms"],
            result=json.loads(row["result"]) if row["result"] else {},
            error=row["error"],
            triggered=bool(row["triggered"]),
            checked_at=row["checked_at"],
        )
