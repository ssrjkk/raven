"""The analytics queries resolve the series the collector actually stores.

`AnalyticsEngine` asked for `raven_messages_received_total` and `raven_tool_calls_success_total` with an
exact `metric_name = ?`, and grouped tool usage with `LIKE '%tool_calls%'`. Neither name exists in the
table: the collector writes one row per label set (`raven_messages_received{channel=webchat}_total`),
and four publishers hand `inc()` a name that already ends in `_total`, so a tool series was stored as
`raven_tool_calls_total{category=fs,tool=read_file}_total`. Every chart on `/analytics` that reads those
answers has been plotting an empty window on a gateway that was busy.

The seeds in `test_analytics_engine.py` were typed by hand in the shape the queries wanted, which is why
the suite stayed green. Here the rows are produced by the same `metrics` singleton the gateway calls and
written by the engine's own snapshot loop, so a rename on either side goes red in this file instead of
silently emptying a chart in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from raven.core import analytics as analytics_mod
from raven.core import analytics_api as analytics_api_mod
from raven.core.analytics import AnalyticsEngine
from raven.core.analytics_api import create_analytics_router, set_analytics_engine
from raven.core.metrics import metrics


class _Clock:
    """A `datetime` stand-in: `_snapshot()` stamps `datetime.now(UTC)`, and two snapshots need two instants."""

    def __init__(self, ts: int) -> None:
        self.ts = ts

    def now(self, _tz: object) -> datetime:
        return datetime.fromtimestamp(self.ts, UTC)


@pytest.fixture
def collector() -> Iterator[None]:
    metrics.clear()
    yield
    metrics.clear()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AnalyticsEngine]:
    e = AnalyticsEngine(tmp_path / "names.db", snapshot_interval=3600)
    await e.start()
    yield e
    await e.stop()


def test_a_counter_named_total_is_stored_once_as_total(collector: None) -> None:
    """`inc()` appends the suffix itself, so a publisher that spells it must not get it twice.

    The exposition surface already collapsed the double suffix (`prometheus_client` strips it), which left
    `/api/metrics` and `/api/metrics/prometheus` disagreeing about which series exist.
    """
    metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    metrics.inc("messages_received", {"channel": "webchat"})
    assert sorted(metrics.snapshot()) == [
        "raven_messages_received{channel=webchat}_total",
        "raven_tool_calls{category=fs,tool=read_file}_total",
    ]


@pytest.mark.asyncio
async def test_aggregated_counts_every_label_set(engine: AnalyticsEngine, collector: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """`received` is the increase of the whole `messages_received` family, summed across channels."""
    clock = _Clock(_aligned_start())
    monkeypatch.setattr(analytics_mod, "datetime", clock)
    metrics.inc("messages_received", {"channel": "webchat"})
    metrics.inc("messages_received", {"channel": "webchat"})
    metrics.inc("message_errors", {"channel": "webchat", "reason": "circuit_breaker"})
    await engine._snapshot()
    clock.ts += 120
    metrics.inc("messages_received", {"channel": "webchat"})
    metrics.inc("messages_received", {"channel": "telegram"})
    metrics.inc("message_errors", {"channel": "telegram", "reason": "provider"})
    await engine._snapshot()

    agg = await engine.query_aggregated(since=clock.ts - 3600)
    assert agg["received"] == 4, "every message the window holds a snapshot of, across both channels"
    assert agg["errors"] == 2
    assert agg["error_rate"] == 50.0
    assert agg["message_series"][-1]["max"] == 4, "the family total, not one channel's counter"
    assert agg["message_series"][-1]["count"] == 2, "two snapshot instants, whatever label sets they carried"


@pytest.mark.asyncio
async def test_a_series_that_begins_inside_the_window_counts_from_zero(
    engine: AnalyticsEngine, collector: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A channel that sent its first message during the window is not a channel that sent nothing.

    Per-bucket max-min reads 0 for a family with one sample, so the first bucket is measured from the
    family's last value before `since` — 0 when the series did not exist yet.
    """
    clock = _Clock(_aligned_start())
    monkeypatch.setattr(analytics_mod, "datetime", clock)
    metrics.inc("messages_received", {"channel": "webchat"})
    await engine._snapshot()
    clock.ts += 60
    metrics.inc("messages_received", {"channel": "telegram"})
    metrics.inc("messages_received", {"channel": "telegram"})
    await engine._snapshot()

    agg = await engine.query_aggregated(since=clock.ts)
    assert agg["received"] == 2, "the telegram series has no sample before the window, so it starts at 0"


@pytest.mark.asyncio
async def test_tool_breakdown_reads_the_publishers_names(
    engine: AnalyticsEngine, collector: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tool_registry` increments `tool_calls_success_total`; the query must find it under either spelling."""
    clock = _Clock(_aligned_start())
    monkeypatch.setattr(analytics_mod, "datetime", clock)
    metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    metrics.inc("tool_calls_success_total", {"tool": "read_file"})
    await engine._snapshot()
    clock.ts += 60
    for _ in range(3):
        metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
        metrics.inc("tool_calls_success_total", {"tool": "read_file"})
    metrics.inc("tool_calls_total", {"tool": "run_python", "category": "exec"})
    metrics.inc("tool_calls_error_total", {"tool": "run_python", "reason": "timeout"})
    await engine._snapshot()

    bd = await engine.query_tool_breakdown(since=clock.ts - 3600)
    assert bd["success"] == 4
    assert bd["errors"] == 1
    assert bd["total"] == 5


@pytest.mark.asyncio
async def test_tool_usage_groups_by_tool_not_by_metric_key(
    engine: AnalyticsEngine, collector: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool charts get a tool name; the labelled metric key never reaches the browser to be parsed.

    `LIKE '%tool_calls%'` also matched `tool_calls_success` and `tool_calls_error`, so the same call was
    counted three times under three names the chart then tried to shorten with `.replace()` on a prefix
    the key did not start with.
    """
    clock = _Clock(_aligned_start())
    monkeypatch.setattr(analytics_mod, "datetime", clock)
    metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    metrics.inc("tool_calls_success_total", {"tool": "read_file"})
    await engine._snapshot()
    clock.ts += 60
    for _ in range(4):
        metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    metrics.inc("tool_calls_total", {"tool": "edit_file", "category": "fs"})
    metrics.inc("tool_calls_error_total", {"tool": "edit_file", "reason": "exception"})
    await engine._snapshot()

    usage = await engine.query_tool_usage(since=clock.ts - 3600)
    assert [(u["name"], u["category"], u["total"]) for u in usage] == [("read_file", "fs", 5), ("edit_file", "fs", 1)]


def _aligned_start() -> int:
    """An instant whose snapshot, and the one a minute later, fall in the same 5-minute bucket.

    Bucketing on wall-clock time would otherwise split the two samples at a boundary and make the run
    depend on the minute the suite started in.
    """
    return (int(datetime.now(UTC).timestamp()) // 300) * 300 + 10


@pytest.mark.asyncio
async def test_the_payload_the_analytics_page_reads_already_names_the_tool(
    engine: AnalyticsEngine, collector: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/analytics/full` over the real engine, because the page shortens nothing any more.

    The endpoint suite mocked `query_tool_usage` as a dict and `query_tool_breakdown` as a list, so it
    stayed green while the browser was handed a whole metric key as a tool name and asked to `.replace()`
    it into something readable.
    """
    clock = _Clock(_aligned_start())
    monkeypatch.setattr(analytics_mod, "datetime", clock)
    metrics.inc("messages_received", {"channel": "webchat"})
    metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    await engine._snapshot()
    clock.ts += 60
    metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
    metrics.inc("tool_calls_success_total", {"tool": "read_file"})
    await engine._snapshot()

    previous = analytics_api_mod._engine
    set_analytics_engine(engine)
    handlers = {
        route.path: route.endpoint
        for route in create_analytics_router().routes
        if isinstance(route, APIRoute)
    }
    try:
        payload = await handlers["/api/analytics/full"]()
    finally:
        analytics_api_mod._engine = previous

    assert [(t["name"], t["category"], t["total"]) for t in payload["tool_usage"]] == [("read_file", "fs", 2)]
    assert payload["tool_breakdown"]["success"] == 1
    assert "{" not in payload["tool_usage"][0]["name"], "a metric key reached the browser as a label"
