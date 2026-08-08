from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite
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
from raven.core.store import BaseStore
from raven.utils.performance import measure_latency

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
    slo_target REAL NOT NULL DEFAULT 0.99,
    slo_window_seconds INTEGER NOT NULL DEFAULT 86400,
    "group" TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_monitor_checks_monitor_id ON monitor_checks(monitor_id);
CREATE INDEX IF NOT EXISTS idx_monitor_checks_mid_at ON monitor_checks(monitor_id, checked_at);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""

_MONITOR_ADDED_COLUMNS = (
    ("slo_target", "ALTER TABLE monitors ADD COLUMN slo_target REAL NOT NULL DEFAULT 0.99"),
    ("slo_window_seconds", "ALTER TABLE monitors ADD COLUMN slo_window_seconds INTEGER NOT NULL DEFAULT 86400"),
    ("group", 'ALTER TABLE monitors ADD COLUMN "group" TEXT NOT NULL DEFAULT \'\''),
)


class MonitorStore(BaseStore):
    SCHEMA = SCHEMA

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)

    async def _post_schema(self, connection: aiosqlite.Connection) -> None:
        existing = {r["name"] for r in await connection.execute_fetchall("PRAGMA table_info(monitors)")}
        for col_name, ddl in _MONITOR_ADDED_COLUMNS:
            if col_name not in existing:
                await connection.execute(ddl)
                logger.info("MonitorStore migration: added column {}", col_name)

    @measure_latency()
    async def save_monitor(self, monitor: Monitor) -> None:
        config = dict(monitor.config)
        config["target"] = monitor.target
        config_json = json.dumps(config)
        conditions_json = json.dumps(
            [{"metric": c.metric, "operator": c.operator.value, "value": c.value} for c in monitor.conditions]
        )
        notify_json = json.dumps(monitor.notify_channels or [])
        await self._execute(
            """INSERT OR REPLACE INTO monitors
               (id, name, type, config, condition, cooldown_minutes,
                interval_seconds, notify_channels, status, user_id, channel,
                slo_target, slo_window_seconds, "group", created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                monitor.slo_target,
                monitor.slo_window_seconds,
                monitor.group,
                monitor.created_at or time.time(),
            ),
        )
        await self._commit()

    @measure_latency()
    async def load_monitor(self, monitor_id: str) -> Monitor | None:
        row = await self._fetchone("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
        if not row:
            return None
        return self._row_to_monitor(row)

    @measure_latency()
    async def delete_monitor(self, monitor_id: str) -> None:
        await self._execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        await self._execute("DELETE FROM monitor_checks WHERE monitor_id = ?", (monitor_id,))
        await self._commit()

    @measure_latency()
    async def list_monitors(
        self, user_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Monitor]:
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
        rows = await self._fetchall(" ".join(parts), params)
        result: list[Monitor] = []
        for r in rows:
            m = self._row_to_monitor(r)
            if m is not None:
                result.append(m)
        return result

    @measure_latency()
    async def count_monitors(self, user_id: str | None = None, status: str | None = None) -> int:
        parts = ["SELECT COUNT(*) as cnt FROM monitors WHERE 1=1"]
        params: list[Any] = []
        if user_id:
            parts.append("AND user_id = ?")
            params.append(user_id)
        if status:
            parts.append("AND status = ?")
            params.append(status)
        row = await self._fetchone(" ".join(parts), params)
        return row["cnt"] if row else 0

    async def list_active(self) -> list[Monitor]:
        return await self.list_monitors(status="active")

    @measure_latency()
    async def get_slo_stats(self, monitor_id: str, window_seconds: int) -> dict[str, int]:
        cutoff = time.time() - window_seconds
        row = await self._fetchone(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END), 0) AS ok_count
               FROM monitor_checks
               WHERE monitor_id = ? AND checked_at >= ?""",
            (monitor_id, cutoff),
        )
        if not row:
            return {"total": 0, "ok": 0, "fail": 0}
        total = int(row["total"] or 0)
        ok = int(row["ok_count"] or 0)
        return {"total": total, "ok": ok, "fail": total - ok}

    @measure_latency()
    async def update_status(self, monitor_id: str, status: MonitorStatus) -> None:
        await self._execute("UPDATE monitors SET status = ? WHERE id = ?", (status.value, monitor_id))
        await self._commit()

    @measure_latency()
    async def get_checks(self, monitor_id: str, limit: int = 20) -> list[MonitorCheck]:
        rows = await self._fetchall(
            "SELECT * FROM monitor_checks WHERE monitor_id = ? ORDER BY checked_at DESC LIMIT ?",
            (monitor_id, limit),
        )
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

    @measure_latency()
    async def save_check(self, check: MonitorCheck) -> None:
        result_json = json.dumps(check.result) if check.result else "{}"
        await self._execute(
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
        await self._execute(
            "UPDATE monitors SET last_checked = ?, last_triggered = ? WHERE id = ?",
            (
                str(check.checked_at or time.time()),
                str(check.checked_at or time.time()) if check.triggered else None,
                check.monitor_id,
            ),
        )
        await self._commit()

    async def save_check_result(self, monitor_id: str, check: CheckResult) -> None:
        mc = MonitorCheck(
            monitor_id=monitor_id,
            status=check.status,
            result={"status": check.status, "response_time_ms": check.response_time_ms},
            error=check.error,
            triggered=check.triggered,
            checked_at=check.checked_at,
            response_time_ms=check.response_time_ms,
        )
        await self.save_check(mc)

    def _row_to_monitor(self, row: aiosqlite.Row) -> Monitor | None:
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
                slo_target=float(row["slo_target"]),
                slo_window_seconds=int(row["slo_window_seconds"]),
                group=row["group"],
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
            try:
                row_id = row["id"]
            except (KeyError, IndexError, TypeError):
                row_id = "unknown"
            logger.warning("Monitor row_to_monitor failed for id={}: {}", row_id, e)
            return None
