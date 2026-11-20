from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.asyncdb import AsyncDB, connect_backend
from raven.core.metrics import metrics

_DB_PATH: Path | None = None

_BUCKET_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}

_METRIC_KEY = re.compile(
    r"^raven_(?P<family>[a-z0-9_]+)(?:\{(?P<labels>[^}]*)\})?"
    r"(?P<suffix>_errors_total|_total|_p99|_max|_avg|_sum|_count)$"
)


def parse_metric_key(name: str) -> tuple[str, dict[str, str], str] | None:
    """Split a `metrics.snapshot()` key into its family, label set and suffix.

    The collector stores one row per label set — `raven_messages_received{channel=webchat}_total` — so a
    query that wants "messages received" has to recognise a family across label sets instead of matching
    a name. Label values are the collector's own unescaped spelling, and `_total`/`_avg`/… are the only
    suffixes `snapshot()` writes.
    """
    match = _METRIC_KEY.match(name)
    if match is None:
        return None
    labels: dict[str, str] = {}
    for pair in (match.group("labels") or "").split(","):
        key, sep, value = pair.rpartition("=")
        if sep:
            labels[key] = value
    return match.group("family"), labels, match.group("suffix")


def _metric_parts(name: str) -> dict[str, Any]:
    """The pieces a reader-facing label is made of, taken from the key the collector stored.

    A browser cannot know where `raven_tool_calls{category=fs,tool=read_file}_total` splits, and the answer
    that assumed it did -- `name.replace("raven_", "")` -- painted `llm_request{model=olla...` on an axis.
    An unparseable key keeps its whole spelling as the family and answers no label, which is the honest
    outcome rather than a wrong one.
    """
    family, labels, suffix = parse_metric_key(name) or (name, {}, "")
    return {"family": family, "stat": suffix.removeprefix("_"), "labels": labels}


def _hour_ago() -> int:
    return int((datetime.now(UTC) - timedelta(hours=1)).timestamp())


def configure(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)


class AnalyticsEngine:
    def __init__(self, db_path: str | Path, snapshot_interval: int = 60) -> None:
        self._db_path = db_path
        self._interval = snapshot_interval
        self._task: asyncio.Task[None] | None = None
        self._db: AsyncDB | None = None

    async def start(self) -> None:
        self._db = connect_backend(self._db_path)
        await self._db.connect()
        await self._ensure_tables()
        self._task = asyncio.create_task(self._loop())
        logger.info("analytics engine started (snapshot every {}s)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._db:
            await self._db.close()
        logger.info("analytics engine stopped")

    async def _ensure_tables(self) -> None:
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        if self._db.dialect == "postgresql":
            await self._db.run_script("""
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    ts BIGINT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value DOUBLE PRECISION NOT NULL
                )
            """)
            await self._db.run_script("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_ts
                ON analytics_snapshots(ts)
            """)
            await self._db.run_script("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_name
                ON analytics_snapshots(metric_name)
            """)
        else:
            await self._db.run_script("""
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL
                )
            """)
            await self._db.run_script("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_ts
                ON analytics_snapshots(ts)
            """)
            await self._db.run_script("""
                CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_name
                ON analytics_snapshots(metric_name)
            """)

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
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        snap = metrics.snapshot()
        now = int(datetime.now(UTC).timestamp())
        rows: list[tuple[int, str, float]] = []
        for name, value in snap.items():
            if isinstance(value, (int, float)):
                rows.append((now, name, float(value)))
        if not rows:
            return
        await self._db.executemany(
            "INSERT INTO analytics_snapshots (ts, metric_name, metric_value) VALUES (?, ?, ?)",
            rows,
        )
        await self._db.commit()

    async def query_series(
        self,
        metric_name: str,
        since: int | None = None,
        bucket: str = "5m",
    ) -> list[dict[str, Any]]:
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        since = since if since is not None else _hour_ago()
        bucket_sec = _BUCKET_SECONDS.get(bucket, 300)
        rows = await self._db.fetchall(
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

    async def _family_members(self, family: str, suffix: str) -> list[tuple[str, dict[str, str]]]:
        """The stored series that belong to one metric family, each with its label set."""
        found: list[tuple[str, dict[str, str]]] = []
        for name in await self.query_metrics_list():
            parsed = parse_metric_key(name)
            if parsed is not None and parsed[0] == family and parsed[2] == suffix:
                found.append((name, parsed[1]))
        return found

    @staticmethod
    def _bucket_points(instants: dict[int, float], bucket_sec: int) -> list[dict[str, Any]]:
        buckets: dict[int, list[float]] = {}
        for ts, value in instants.items():
            buckets.setdefault((ts // bucket_sec) * bucket_sec, []).append(value)
        return [
            {
                "ts": bucket_ts,
                "avg": round(sum(vals) / len(vals), 2),
                "max": round(max(vals), 2),
                "min": round(min(vals), 2),
                "count": len(vals),
            }
            for bucket_ts, vals in sorted(buckets.items())
        ]

    async def _merged_series(self, names: list[str], since: int, bucket: str) -> list[dict[str, Any]]:
        """A family's points across every label set: the value at an instant is the sum over its members.

        `channel=webchat` and `channel=telegram` are two rows of one fact at the same instant, and the
        charts want the fact. Merging raw rows rather than bucket statistics is what keeps `max - min`
        the increase of the family instead of the spread of whichever channel reported last.
        """
        if not names:
            return []
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        if len(names) == 1:
            return await self.query_series(names[0], since=since, bucket=bucket)
        instants: dict[int, float] = {}
        for name in names:
            rows = await self._db.fetchall(
                "SELECT ts, metric_value FROM analytics_snapshots WHERE metric_name = ? AND ts >= ? ORDER BY ts",
                (name, since),
            )
            for row in rows:
                instants[row[0]] = instants.get(row[0], 0.0) + float(row[1])
        return self._bucket_points(instants, _BUCKET_SECONDS.get(bucket, 300))

    async def _baseline(self, names: list[str], before: int) -> float:
        """Where the family stood when a window opened: each member's last value before `before`, or 0."""
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        total = 0.0
        for name in names:
            row = await self._db.fetchone(
                "SELECT metric_value FROM analytics_snapshots WHERE metric_name = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
                (name, before),
            )
            if row is not None:
                total += float(row[0])
        return total

    @staticmethod
    def _increase(series: list[dict[str, Any]], baseline: float) -> float:
        """What a window saw of a cumulative counter.

        Per-bucket max-min is what survives a process restart, but it reads 0 for a bucket holding a
        single sample — the channel that reported once, the tool called once — which is what a freshly
        started gateway looks like. So the first bucket is measured from where the family stood when the
        window opened.
        """
        if not series:
            return 0.0
        later = sum(point["max"] - point["min"] for point in series[1:])
        first = series[0]
        return float(later + max(0.0, first["max"] - min(first["min"], baseline)))

    async def query_family(
        self,
        family: str,
        since: int | None = None,
        bucket: str = "5m",
        suffix: str = "_total",
    ) -> dict[str, Any]:
        """One metric family merged across its label sets: the points to plot and the increase to print.

        `family` is the name a publisher gave `metrics.inc()` without the `_total` the collector appends,
        so a query cannot outlive a rename on the publishing side.
        """
        since = since if since is not None else _hour_ago()
        members = [name for name, _ in await self._family_members(family, suffix)]
        series = await self._merged_series(members, since, bucket)
        return {
            "family": family,
            "series": series,
            "increase": self._increase(series, await self._baseline(members, since)),
            "label_sets": len(members),
        }

    async def query_metrics_list(self) -> list[str]:
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        rows = await self._db.fetchall("SELECT DISTINCT metric_name FROM analytics_snapshots ORDER BY metric_name")
        return [r[0] for r in rows]

    async def query_summary(self, since: int | None = None) -> dict[str, Any]:
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        since = since if since is not None else _hour_ago()
        totals = await self._db.fetchall(
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
        total_points = await self._db.fetchall(
            "SELECT COUNT(*) AS c FROM analytics_snapshots WHERE ts >= ?",
            (since,),
        )
        oldest = await self._db.fetchall("SELECT MIN(ts) AS t FROM analytics_snapshots")
        data_rows = [
            {
                **_metric_parts(r[0]),
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
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        since = since if since is not None else _hour_ago()
        received = await self.query_family("messages_received", since=since)
        errors = await self.query_family("message_errors", since=since)
        rows = await self._db.fetchall(
            "SELECT DISTINCT metric_name FROM analytics_snapshots "
            "WHERE metric_name LIKE '%latency%' OR metric_name LIKE '%response%' "
            "OR metric_name LIKE '%p99%' ORDER BY metric_name"
        )
        # A shaped list, not a map keyed by the metric key: the page titles these charts from `name` and
        # `labels`, and a `Record` gave it `raven_llm_request{model=…,provider=…}_p99` to print verbatim.
        # A shaped list, not a map keyed by the metric key: the page titles these charts from `family` and
        # `labels`, and handing it the key painted `raven_llm_request{model=…,provider=…}_p99` as a heading.
        latency_series = [
            {**_metric_parts(row[0]), "metric": row[0], "series": await self.query_series(row[0], since=since)}
            for row in rows
        ]
        total_received = received["increase"]
        total_errors = errors["increase"]
        return {
            "received": round(total_received),
            "errors": round(total_errors),
            "error_rate": round(total_errors / total_received * 100, 2) if total_received > 0 else 0,
            "message_series": received["series"],
            "error_series": errors["series"],
            "latency_series": latency_series,
            "since": since,
        }

    async def query_tool_usage(self, since: int | None = None) -> list[dict[str, Any]]:
        """Calls per tool, grouped by the `tool` label the publishers attach.

        `LIKE '%tool_calls%'` used to hand back the tool, its successes and its errors as three different
        "tools" named by whole metric keys, which the browser then shortened by hand — and it summed
        `avg x count` over a cumulative counter, so the bars were inflated by the sampling rate.
        """
        since = since if since is not None else _hour_ago()
        members: dict[str, list[str]] = {}
        categories: dict[str, set[str]] = {}
        for name, labels in await self._family_members("tool_calls", "_total"):
            tool = labels.get("tool") or "tool_calls"
            members.setdefault(tool, []).append(name)
            category = labels.get("category")
            if category:
                categories.setdefault(tool, set()).add(category)
        results: list[dict[str, Any]] = []
        for tool, names in members.items():
            series = await self._merged_series(names, since, "5m")
            total = self._increase(series, await self._baseline(names, since))
            if total > 0:
                results.append(
                    {
                        "name": tool,
                        "category": ",".join(sorted(categories.get(tool, ()))),
                        "total": round(total),
                        "series": series,
                    }
                )
        results.sort(key=lambda r: (-r["total"], r["name"]))
        return results

    async def query_tool_breakdown(self, since: int | None = None) -> dict[str, Any]:
        if self._db is None:
            raise RuntimeError("AnalyticsEngine not started")
        since = since if since is not None else _hour_ago()
        success = await self.query_family("tool_calls_success", since=since)
        errors = await self.query_family("tool_calls_error", since=since)
        return {
            "success": round(success["increase"]),
            "errors": round(errors["increase"]),
            "total": round(success["increase"] + errors["increase"]),
            "success_series": success["series"],
            "error_series": errors["series"],
        }
