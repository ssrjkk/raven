from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core import analytics as analytics_mod
from raven.core.analytics import AnalyticsEngine, configure
from raven.core.metrics import metrics


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


async def _seed(engine: AnalyticsEngine, rows: list[tuple[int, str, float]]) -> None:
    """Put rows in the table the way `_snapshot()` would, with the keys the collector spells.

    The birth of those keys is `test_analytics_metric_names.py`'s job; this file tests the aggregation.
    """
    db = engine._db
    assert db is not None
    await db.executemany(
        "INSERT INTO analytics_snapshots (ts, metric_name, metric_value) VALUES (?, ?, ?)",
        rows,
    )
    await db.commit()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AnalyticsEngine, None]:
    e = AnalyticsEngine(tmp_path / "analytics.db", snapshot_interval=3600)
    await e.start()
    yield e
    await e.stop()


def test_configure_sets_global(tmp_path: Path) -> None:
    original = analytics_mod._DB_PATH
    expected = tmp_path / "cfg.db"
    try:
        configure(expected)
        assert expected == analytics_mod._DB_PATH
    finally:
        analytics_mod._DB_PATH = original


@pytest.mark.asyncio
async def test_start_creates_tables_and_stop(tmp_path: Path) -> None:
    e = AnalyticsEngine(tmp_path / "a.db", snapshot_interval=3600)
    await e.start()
    assert e._db is not None
    assert e._task is not None
    # query on the freshly created (empty) table proves the schema exists
    assert await e.query_metrics_list() == []
    await e.stop()
    assert e._task is not None and e._task.done()


@pytest.mark.asyncio
async def test_stop_without_start_is_noop() -> None:
    e = AnalyticsEngine("unused.db")
    await e.stop()  # must not raise even though _task and _db are None


@pytest.mark.asyncio
async def test_ensure_tables_postgres_branch() -> None:
    e = AnalyticsEngine("x")
    db = MagicMock()
    db.dialect = "postgresql"
    db.run_script = AsyncMock()
    e._db = db
    await e._ensure_tables()
    assert db.run_script.await_count == 3


@pytest.mark.asyncio
async def test_guards_raise_when_not_started() -> None:
    e = AnalyticsEngine("x.db")
    with pytest.raises(RuntimeError):
        await e._ensure_tables()
    with pytest.raises(RuntimeError):
        await e._snapshot()
    with pytest.raises(RuntimeError):
        await e.query_series("m")
    with pytest.raises(RuntimeError):
        await e.query_metrics_list()
    with pytest.raises(RuntimeError):
        await e.query_summary()
    with pytest.raises(RuntimeError):
        await e.query_aggregated()
    with pytest.raises(RuntimeError):
        await e.query_tool_usage()


@pytest.mark.asyncio
async def test_snapshot_filters_nonnumeric(engine: AnalyticsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "snapshot", lambda: {"keep_total": 5, "skip_str": "x", "avg_v": 1.5})
    await engine._snapshot()
    assert sorted(await engine.query_metrics_list()) == ["avg_v", "keep_total"]


@pytest.mark.asyncio
async def test_snapshot_no_numeric_rows_returns_early(engine: AnalyticsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "snapshot", lambda: {"only": "text"})
    await engine._snapshot()
    assert await engine.query_metrics_list() == []


@pytest.mark.asyncio
async def test_query_series_aggregates(engine: AnalyticsEngine) -> None:
    base = (_now() // 86400) * 86400
    await _seed(engine, [(base + 10, "m", 1.0), (base + 20, "m", 3.0), (base + 15, "other", 9.0)])
    series = await engine.query_series("m", since=base, bucket="1d")
    assert len(series) == 1
    point = series[0]
    assert point["avg"] == 2.0
    assert point["max"] == 3.0
    assert point["min"] == 1.0
    assert point["count"] == 2


@pytest.mark.asyncio
async def test_query_series_default_since(engine: AnalyticsEngine) -> None:
    now = _now()
    await _seed(engine, [(now - 60, "recent", 2.0)])
    series = await engine.query_series("recent")
    assert series and series[0]["count"] == 1


@pytest.mark.asyncio
async def test_query_summary_populated(engine: AnalyticsEngine) -> None:
    base = _now() - 3600
    await _seed(engine, [(base + 10, "alpha", 1.0), (base + 20, "alpha", 3.0), (base + 30, "beta", 5.0)])
    summary = await engine.query_summary(since=base)
    assert summary["total_data_points"] == 3
    assert summary["oldest_record_ts"] == base + 10
    names = {m["name"] for m in summary["metrics"]}
    assert names == {"alpha", "beta"}
    alpha = next(m for m in summary["metrics"] if m["name"] == "alpha")
    assert alpha["avg"] == 2.0 and alpha["max"] == 3.0 and alpha["samples"] == 2


@pytest.mark.asyncio
async def test_query_summary_empty(engine: AnalyticsEngine) -> None:
    summary = await engine.query_summary(since=_now() - 10)
    assert summary["metrics"] == []
    assert summary["total_data_points"] == 0
    assert summary["oldest_record_ts"] is None


@pytest.mark.asyncio
async def test_query_aggregated(engine: AnalyticsEngine) -> None:
    base = (_now() // 300) * 300
    await _seed(
        engine,
        [
            (base + 10, "raven_messages_received{channel=webchat}_total", 0.0),
            (base + 20, "raven_messages_received{channel=webchat}_total", 10.0),
            (base + 10, "raven_message_errors{channel=webchat}_total", 0.0),
            (base + 20, "raven_message_errors{channel=webchat}_total", 2.0),
            (base + 10, "raven_llm_latency{model=qwen}_avg", 5.0),
        ],
    )
    agg = await engine.query_aggregated(since=base)
    assert agg["received"] == 10
    assert agg["errors"] == 2
    assert agg["error_rate"] == 20.0
    assert [(e["family"], e["stat"], e["labels"]) for e in agg["latency_series"]] == [
        ("llm_latency", "avg", {"model": "qwen"})
    ], "the chart is given the parts of a title, not the metric key it would have to parse"


@pytest.mark.asyncio
async def test_query_aggregated_zero_received(engine: AnalyticsEngine) -> None:
    agg = await engine.query_aggregated(since=_now())
    assert agg["received"] == 0
    assert agg["error_rate"] == 0


@pytest.mark.asyncio
async def test_query_tool_usage(engine: AnalyticsEngine) -> None:
    base = (_now() // 86400) * 86400
    await _seed(
        engine,
        [
            (base + 10, "raven_tool_calls{category=fs,tool=read}_total", 0.0),
            (base + 20, "raven_tool_calls{category=fs,tool=read}_total", 5.0),
            (base + 10, "raven_tool_calls{category=fs,tool=zero}_total", 0.0),
            (base + 20, "raven_tool_calls_success{tool=read}_total", 4.0),
            (base + 20, "raven_not_a_tool{thing=x}_total", 9.0),
        ],
    )
    usage = await engine.query_tool_usage(since=base)
    assert [(u["name"], u["category"], u["total"]) for u in usage] == [("read", "fs", 5)]


@pytest.mark.asyncio
async def test_query_tool_breakdown(engine: AnalyticsEngine) -> None:
    base = (_now() // 300) * 300
    await _seed(
        engine,
        [
            (base + 10, "raven_tool_calls_success{tool=read}_total", 0.0),
            (base + 20, "raven_tool_calls_success{tool=read}_total", 3.0),
            (base + 10, "raven_tool_calls_error{reason=timeout,tool=run}_total", 0.0),
            (base + 20, "raven_tool_calls_error{reason=timeout,tool=run}_total", 1.0),
        ],
    )
    bd = await engine.query_tool_breakdown(since=base)
    assert bd["success"] == 3
    assert bd["errors"] == 1
    assert bd["total"] == 4


@pytest.mark.asyncio
async def test_loop_snapshots_and_survives_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    e = AnalyticsEngine(tmp_path / "loop.db", snapshot_interval=0)
    calls = {"n": 0}

    async def fake_snapshot() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    await e.start()
    e._snapshot = fake_snapshot  # type: ignore[method-assign]
    try:
        for _ in range(300):
            if calls["n"] >= 2:
                break
            await asyncio.sleep(0.01)
        assert calls["n"] >= 2
        assert e._task is not None and not e._task.done()
    finally:
        await e.stop()
    assert e._task is not None and e._task.done()


@pytest.mark.asyncio
async def test_loop_survives_watch_error(tmp_path: Path) -> None:
    e = AnalyticsEngine(tmp_path / "err.db", snapshot_interval=0)

    async def explode() -> None:
        raise OSError("disk gone")

    e._snapshot = explode  # type: ignore[method-assign]
    await e.start()
    try:
        await asyncio.sleep(0.05)
        assert e._task is not None and not e._task.done()
    finally:
        await e.stop()
