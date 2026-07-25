from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from raven.core.analytics import AnalyticsEngine

_engine: AnalyticsEngine | None = None


def set_analytics_engine(engine: AnalyticsEngine) -> None:
    global _engine
    _engine = engine


def _get_engine() -> AnalyticsEngine:
    if _engine is None:
        raise RuntimeError("analytics engine not initialized")
    return _engine


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/api/analytics", tags=["analytics"])

    @router.get("/metrics")
    async def list_metrics():
        eng = _get_engine()
        return {"metrics": await eng.query_metrics_list()}

    @router.get("/series/{metric_name}")
    async def get_series(
        metric_name: str,
        since: int | None = Query(None, description="Unix timestamp"),
        bucket: str = Query("5m", description="Bucket: 1m, 5m, 15m, 1h, 1d"),
    ):
        eng = _get_engine()
        return {"metric": metric_name, "data": await eng.query_series(metric_name, since=since, bucket=bucket)}

    @router.get("/summary")
    async def get_summary(since: int | None = Query(None)):
        eng = _get_engine()
        return await eng.query_summary(since=since)

    @router.get("/aggregated")
    async def get_aggregated(since: int | None = Query(None)):
        eng = _get_engine()
        return await eng.query_aggregated(since=since)

    @router.get("/overview")
    async def get_overview():
        eng = _get_engine()
        since_1h = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        since_24h = int((datetime.now(UTC) - timedelta(days=1)).timestamp())
        h1 = await eng.query_aggregated(since=since_1h)
        h24 = await eng.query_aggregated(since=since_24h)
        return {"last_hour": h1, "last_24h": h24}

    @router.get("/tools/usage")
    async def get_tool_usage(since: int | None = Query(None)):
        eng = _get_engine()
        return {"tools": await eng.query_tool_usage(since=since)}

    @router.get("/tools/breakdown")
    async def get_tool_breakdown(since: int | None = Query(None)):
        eng = _get_engine()
        return await eng.query_tool_breakdown(since=since)

    @router.get("/full")
    async def get_full_overview():
        eng = _get_engine()
        since_1h = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        since_24h = int((datetime.now(UTC) - timedelta(days=1)).timestamp())
        h1 = await eng.query_aggregated(since=since_1h)
        h24 = await eng.query_aggregated(since=since_24h)
        summary = await eng.query_summary(since=since_24h)
        tool_breakdown = await eng.query_tool_breakdown(since=since_24h)
        tool_usage = await eng.query_tool_usage(since=since_24h)
        h1_tools = await eng.query_tool_usage(since=since_1h)
        return {
            "last_hour": h1,
            "last_24h": h24,
            "summary": summary,
            "tool_breakdown": tool_breakdown,
            "tool_usage": tool_usage,
            "tool_usage_1h": h1_tools,
        }

    return router
