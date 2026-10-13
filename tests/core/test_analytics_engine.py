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
            (base + 10, "raven_messages_received_total", 0.0),
            (base + 20, "raven_messages_received_total", 10.0),
            (base + 10, "raven_message_errors_total", 0.0),
            (base + 20, "raven_message_errors_total", 2.0),
            (base + 10, "raven_response_latency_avg", 5.0),
        ],
    )
    agg = await engine.query_aggregated(since=base)
    assert agg["received"] == 10
    assert agg["errors"] == 2
    assert agg["error_rate"] == 20.0
    assert "raven_response_latency_avg" in agg["latency_series"]


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
            (base + 10, "read_tool_calls_total", 3.0),
            (base + 20, "read_tool_calls_total", 5.0),
            (base + 10, "zero_tool_calls_total", 0.0),
            (base + 10, "not_a_tool_total", 9.0),
        ],
    )
    usage = await engine.query_tool_usage(since=base)
    names = {u["name"] for u in usage}
    assert names == {"read_tool_calls_total"}
    assert usage[0]["total"] == 8  # avg 4 * count 2


@pytest.mark.asyncio
async def test_query_tool_breakdown(engine: AnalyticsEngine) -> None:
    base = (_now() // 300) * 300
    await _seed(
        engine,
        [
            (base + 10, "raven_tool_calls_success_total", 1.0),
            (base + 20, "raven_tool_calls_success_total", 4.0),
            (base + 10, "raven_tool_calls_error_total", 0.0),
            (base + 20, "raven_tool_calls_error_total", 1.0),
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
