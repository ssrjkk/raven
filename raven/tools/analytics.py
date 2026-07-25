from __future__ import annotations

from datetime import UTC, datetime, timedelta

from raven.core.analytics import AnalyticsEngine
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_engine: AnalyticsEngine | None = None


def set_analytics_engine(engine: AnalyticsEngine) -> None:
    global _engine
    _engine = engine


def _get_engine() -> AnalyticsEngine:
    if _engine is None:
        raise RuntimeError("analytics engine not initialized")
    return _engine


async def analytics_metrics_list() -> str:
    eng = _get_engine()
    metrics = await eng.query_metrics_list()
    if not metrics:
        return "[info] No metrics collected yet."
    lines = [f"Available metrics ({len(metrics)}):"]
    for m in metrics:
        lines.append(f"  - {m}")
    return "\n".join(lines)


async def analytics_series(metric_name: str, bucket: str = "5m", hours: int = 1) -> str:
    eng = _get_engine()
    since = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())
    data = await eng.query_series(metric_name, since=since, bucket=bucket)
    if not data:
        return f"[info] No data for '{metric_name}' in the last {hours}h."
    lines = [f"Time series: {metric_name} (past {hours}h, bucket={bucket})"]
    for d in data[-20:]:
        lines.append(f"  [{d['ts']}] avg={d['avg']}, max={d['max']}, min={d['min']} (n={d['count']})")
    return "\n".join(lines)


async def analytics_summary(hours: int = 1) -> str:
    eng = _get_engine()
    since = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())
    summary = await eng.query_summary(since=since)
    lines = [f"Analytics Summary (past {hours}h):"]
    for m in summary["metrics"]:
        lines.append(f"  {m['name']}: avg={m['avg']}, max={m['max']}, samples={m['samples']}")
    lines.append(f"Total data points: {summary['total_data_points']}")
    if summary["oldest_record_ts"]:
        oldest = datetime.fromtimestamp(summary["oldest_record_ts"], tz=UTC)
        lines.append(f"Oldest record: {oldest.isoformat()}")
    return "\n".join(lines)


async def analytics_overview() -> str:
    eng = _get_engine()
    since_1h = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    since_24h = int((datetime.now(UTC) - timedelta(days=1)).timestamp())
    h1 = await eng.query_aggregated(since=since_1h)
    h24 = await eng.query_aggregated(since=since_24h)
    return (
        f"Analytics Overview\n"
        f"━━━ Last Hour ━━━\n"
        f"  Messages received: {h1['received']}\n"
        f"  Errors: {h1['errors']} ({h1['error_rate']}%)\n"
        f"━━━ Last 24 Hours ━━━\n"
        f"  Messages received: {h24['received']}\n"
        f"  Errors: {h24['errors']} ({h24['error_rate']}%)\n"
    )


def register_analytics_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="analytics_metrics_list",
            description="List all available analytics metric names",
            parameters={},
            handler=analytics_metrics_list,
            category="analytics",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="analytics_series",
            description="Get time-series data for a specific metric",
            parameters={
                "metric_name": {"type": "string", "description": "Metric name", "required": True},
                "bucket": {
                    "type": "string",
                    "description": "Bucket size: 1m, 5m, 15m, 1h, 1d (default 5m)",
                    "required": False,
                },
                "hours": {"type": "number", "description": "Hours of history (default 1)", "required": False},
            },
            handler=analytics_series,
            category="analytics",
            timeout=15,
        )
    )
    registry.register(
        ToolSpec(
            name="analytics_summary",
            description="Get summary stats for all metrics",
            parameters={
                "hours": {"type": "number", "description": "Hours of history (default 1)", "required": False},
            },
            handler=analytics_summary,
            category="analytics",
            timeout=15,
        )
    )
    registry.register(
        ToolSpec(
            name="analytics_overview",
            description="Get high-level analytics overview (last hour + last 24h)",
            parameters={},
            handler=analytics_overview,
            category="analytics",
            timeout=10,
        )
    )
