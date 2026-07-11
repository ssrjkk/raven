from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from raven.core.metrics import metrics

_DB_PATH: Path | None = None


def configure(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)


class AnalyticsEngine:
    def __init__(self, db_path: str | Path, snapshot_interval: int = 60) -> None:
        self._db_path = Path(db_path)
        self._interval = snapshot_interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._ensure_tables()
        self._task = asyncio.create_task(self._loop())
        logger.info("analytics engine started (snapshot every {}s)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("analytics engine stopped")

    async def _ensure_tables(self) -> None:
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_ts
                ON analytics_snapshots(ts)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_name
                ON analytics_snapshots(metric_name)
            """)
            await db.commit()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("analytics snapshot error: {}", e)

    async def _snapshot(self) -> None:
        snap = metrics.snapshot()
        now = int(datetime.now(UTC).timestamp())
        rows: list[tuple[int, str, float]] = []
        for name, value in snap.items():
            if isinstance(value, (int, float)):
                rows.append((now, name, float(value)))
        if not rows:
            return
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executemany(
                "INSERT INTO analytics_snapshots (ts, metric_name, metric_value) VALUES (?, ?, ?)",
                rows,
            )
            await db.commit()

    async def query_series(
        self,
        metric_name: str,
        since: int | None = None,
        bucket: str = "5m",
    ) -> list[dict[str, Any]]:
        since = since or int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        bucket_sec = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}.get(bucket, 300)
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT
                    (ts / ?) * ? AS bucket_ts,
                    AVG(metric_value) AS avg_val,
                    MAX(metric_value) AS max_val,
                    MIN(metric_value) AS min_val,
                    COUNT(*) AS sample_count
                FROM analytics_snapshots
                WHERE metric_name = ? AND ts >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts ASC
                """,
                (bucket_sec, bucket_sec, metric_name, since),
            )
            return [
                {
                    "ts": r[0],
                    "avg": round(r[1], 2) if r[1] is not None else 0,
                    "max": round(r[2], 2) if r[2] is not None else 0,
                    "min": round(r[3], 2) if r[3] is not None else 0,
                    "count": r[4],
                }
                for r in rows
            ]

    async def query_metrics_list(self) -> list[str]:
        async with aiosqlite.connect(str(self._db_path)) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT metric_name FROM analytics_snapshots ORDER BY metric_name"
            )
            return [r[0] for r in rows]

    async def query_summary(self, since: int | None = None) -> dict[str, Any]:
        since = since or int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            totals = await db.execute_fetchall(
                """
                SELECT metric_name, AVG(metric_value) AS avg_val,
                       MAX(metric_value) AS max_val, COUNT(*) AS cnt
                FROM analytics_snapshots
                WHERE ts >= ?
                GROUP BY metric_name
                ORDER BY metric_name
                """,
                (since,),
            )
            total_points = list(
                await db.execute_fetchall(
                    "SELECT COUNT(*) AS c FROM analytics_snapshots WHERE ts >= ?",
                    (since,),
                )
            )
            oldest = list(
                await db.execute_fetchall(
                    "SELECT MIN(ts) AS t FROM analytics_snapshots"
                )
            )
        data_rows = [
            {
                "name": r[0],
                "avg": round(r[1], 2) if r[1] is not None else 0,
                "max": round(r[2], 2) if r[2] is not None else 0,
                "samples": r[3],
            }
            for r in totals
        ]
        return {
            "metrics": data_rows,
            "total_data_points": total_points[0][0] if total_points else 0,
            "oldest_record_ts": oldest[0][0] if oldest and oldest[0][0] else None,
            "since": since,
        }

    async def query_aggregated(self, since: int | None = None) -> dict[str, Any]:
        since = since or int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        series = await self.query_series("raven_messages_received_total", since=since)
        error_series = await self.query_series("raven_message_errors_total", since=since)
        total_received = sum(s["avg"] * s["count"] for s in series) if series else 0
        total_errors = sum(s["avg"] * s["count"] for s in error_series) if error_series else 0
        async with aiosqlite.connect(str(self._db_path)) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT metric_name FROM analytics_snapshots WHERE metric_name LIKE '%latency%' OR metric_name LIKE '%response%' OR metric_name LIKE '%p99%'"
            )
            latency_series = {}
            for r in rows:
                latency_series[r[0]] = await self.query_series(r[0], since=since)
        return {
            "received": round(total_received),
            "errors": round(total_errors),
            "error_rate": round(total_errors / total_received * 100, 2) if total_received > 0 else 0,
            "message_series": series,
            "error_series": error_series,
            "latency_series": latency_series,
            "since": since,
        }

    async def query_tool_usage(self, since: int | None = None) -> list[dict[str, Any]]:
        since = since or int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        async with aiosqlite.connect(str(self._db_path)) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT metric_name FROM analytics_snapshots WHERE metric_name LIKE '%tool_calls%' AND ts >= ?",
                (since,),
            )
        results: list[dict[str, Any]] = []
        for row in rows:
            name = row[0]
            series = await self.query_series(name, since=since)
            total = sum(s["avg"] * s["count"] for s in series) if series else 0
            if total > 0:
                results.append({
                    "name": name,
                    "total": round(total),
                    "series": series,
                })
        results.sort(key=lambda r: r["total"], reverse=True)
        return results

    async def query_tool_breakdown(self, since: int | None = None) -> dict[str, Any]:
        since = since or int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        success = await self.query_series("raven_tool_calls_success_total", since=since)
        error_s = await self.query_series("raven_tool_calls_error_total", since=since)
        total_success = sum(s["avg"] * s["count"] for s in success) if success else 0
        total_errors = sum(s["avg"] * s["count"] for s in error_s) if error_s else 0
        return {
            "success": round(total_success),
            "errors": round(total_errors),
            "total": round(total_success + total_errors),
            "success_series": success,
            "error_series": error_s,
        }



