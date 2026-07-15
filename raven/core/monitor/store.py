from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core._json import json
from raven.core.monitor.models import (
    CheckResult,
    Condition,
    ConditionOperator,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    MonitorType,
)

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn  # type: ignore[no-any-return]


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('price','http','rss','file','process')),
    config TEXT NOT NULL DEFAULT '{}',
    condition TEXT NOT NULL DEFAULT '',
    cooldown_minutes INTEGER NOT NULL DEFAULT 30,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    notify_channels TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    last_checked TEXT,
    last_triggered TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitor_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    checked_at REAL NOT NULL,
    response_time_ms REAL,
    triggered INTEGER DEFAULT 0,
    result TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_monitor_status ON monitors(status);
CREATE INDEX IF NOT EXISTS idx_monitor_user_id ON monitors(user_id);
CREATE INDEX IF NOT EXISTS idx_monitor_checks_monitor_id ON monitor_checks(monitor_id);
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

    def save_monitor(self, monitor: Monitor):
        conn = self._conn()
        config = dict(monitor.config)
        config["target"] = monitor.target
        config_json = json.dumps(config)
        conditions_json = json.dumps(
            [{"metric": c.metric, "operator": c.operator.value, "value": c.value} for c in monitor.conditions]
        )
        notify_json = json.dumps(monitor.notify_channels or [])
        conn.execute(
            """INSERT OR REPLACE INTO monitors
               (id, name, type, config, condition, cooldown_minutes,
                interval_seconds, notify_channels, status, user_id, channel, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                monitor.id,
                monitor.name,
                monitor.type.value,
                config_json,
                conditions_json,
                monitor.cooldown_minutes,
                monitor.interval_seconds,
                notify_json,
                monitor.status.value,
                monitor.user_id,
                monitor.channel,
                monitor.created_at or time.time(),
            ),
        )
        conn.commit()

    def load_monitor(self, monitor_id: str) -> Monitor | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
        if not row:
            return None
        return self._row_to_monitor(row)

    def delete_monitor(self, monitor_id: str):
        conn = self._conn()
        conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        conn.execute("DELETE FROM monitor_checks WHERE monitor_id = ?", (monitor_id,))
        conn.commit()

    def list_monitors(self, user_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> list[Monitor]:
        conn = self._conn()
        parts = ["SELECT * FROM monitors WHERE 1=1"]
        params: list[Any] = []
        if user_id:
            parts.append("AND user_id = ?")
            params.append(user_id)
        if status:
            parts.append("AND status = ?")
            params.append(status)
        parts.append("ORDER BY created_at DESC LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        rows = conn.execute(" ".join(parts), params).fetchall()
        return [m for r in rows if (m := self._row_to_monitor(r)) is not None]

    def list_active(self) -> list[Monitor]:
        return self.list_monitors(status="active")

    def update_status(self, monitor_id: str, status: MonitorStatus):
        conn = self._conn()
        conn.execute(
            "UPDATE monitors SET status = ? WHERE id = ?",
            (status.value, monitor_id),
        )
        conn.commit()

    def get_checks(self, monitor_id: str, limit: int = 20) -> list[MonitorCheck]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM monitor_checks WHERE monitor_id = ? ORDER BY checked_at DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
        return [
            MonitorCheck(
                id=str(r["id"]),
                monitor_id=r["monitor_id"],
                status=r["status"],
                result=json.loads(r["result"]) if r["result"] else {},
                error=r["error"],
                triggered=bool(r["triggered"]),
                checked_at=r["checked_at"],
                response_time_ms=r["response_time_ms"],
            )
            for r in rows
        ]

    def save_check(self, check: MonitorCheck):
        conn = self._conn()
        result_json = json.dumps(check.result) if check.result else "{}"
        conn.execute(
            """INSERT INTO monitor_checks
               (monitor_id, status, checked_at, response_time_ms, triggered, result, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                check.monitor_id,
                check.status,
                check.checked_at or time.time(),
                check.response_time_ms,
                int(check.triggered),
                result_json,
                check.error,
            ),
        )
        conn.execute(
            "UPDATE monitors SET last_checked = ?, last_triggered = ? WHERE id = ?",
            (
                str(check.checked_at or time.time()),
                str(check.checked_at or time.time()) if check.triggered else None,
                check.monitor_id,
            ),
        )
        conn.commit()

    def save_check_result(self, monitor_id: str, check: CheckResult):
        mc = MonitorCheck(
            monitor_id=monitor_id,
            status=check.status,
            result={"status": check.status, "response_time_ms": check.response_time_ms},
            error=check.error,
            triggered=check.triggered,
            checked_at=check.checked_at,
            response_time_ms=check.response_time_ms,
        )
        self.save_check(mc)

    def _row_to_monitor(self, row: sqlite3.Row) -> Monitor | None:
        try:
            config = json.loads(row["config"]) if row["config"] else {}
            conditions_raw = json.loads(row["condition"]) if row["condition"] else []
            conditions = []
            for c in conditions_raw:
                conditions.append(
                    Condition(
                        metric=c["metric"],
                        operator=ConditionOperator(c.get("operator", "=")),
                        value=c["value"],
                    )
                )
            notify = json.loads(row["notify_channels"]) if row["notify_channels"] else []

            m = Monitor(
                id=row["id"],
                name=row["name"],
                type=MonitorType(row["type"]),
                target=config.get("target", ""),
                interval_seconds=row["interval_seconds"],
                status=MonitorStatus(row["status"]),
                conditions=conditions,
                notify_channels=notify,
                cooldown_minutes=row["cooldown_minutes"],
                config=config,
                user_id=row["user_id"],
                channel=row["channel"],
                created_at=row["created_at"],
            )

            last_checked = row["last_checked"]
            if last_checked:
                last_triggered = row["last_triggered"]
                m.last_check = CheckResult(
                    status="up",
                    checked_at=float(last_checked),
                    triggered=last_triggered is not None,
                )
            return m
        except Exception as e:
            logger.warning("Monitor load failed: {}", e)
            return None
