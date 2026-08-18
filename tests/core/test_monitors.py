from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.monitor.alert import AlertDispatcher
from raven.core.monitor.conditions import ConditionEvaluator
from raven.core.monitor.engine import MonitorEngine
from raven.core.monitor.models import (
    CheckResult,
    Condition,
    ConditionOperator,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    MonitorType,
    SLOStats,
)
from raven.core.monitor.store import MonitorStore


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "monitors.db")


@pytest.fixture
async def store(db_path: str):
    s = MonitorStore(db_path)
    yield s
    await s.close()


@pytest.fixture
def monitor() -> Monitor:
    return Monitor(
        name="test-http",
        type=MonitorType.HTTP,
        target="https://example.com",
        interval_seconds=3600,
        status=MonitorStatus.ACTIVE,
    )


class TestMonitorStore:
    @pytest.mark.asyncio
    async def test_save_and_load(self, store: MonitorStore, monitor: Monitor):
        await store.save_monitor(monitor)
        loaded = await store.load_monitor(monitor.id)
        assert loaded is not None
        assert loaded.name == "test-http"
        assert loaded.type == MonitorType.HTTP
        assert loaded.target == "https://example.com"

    @pytest.mark.asyncio
    async def test_save_and_load_with_conditions(self, store: MonitorStore):
        m = Monitor(
            name="price-check",
            type=MonitorType.PRICE,
            target="bitcoin",
            conditions=[Condition(metric="price", operator=ConditionOperator.GT, value="50000")],
        )
        await store.save_monitor(m)
        loaded = await store.load_monitor(m.id)
        assert loaded is not None
        assert len(loaded.conditions) == 1
        assert loaded.conditions[0].metric == "price"
        assert loaded.conditions[0].operator == ConditionOperator.GT

    @pytest.mark.asyncio
    async def test_list_active(self, store: MonitorStore):
        a = Monitor(name="active-1", type=MonitorType.HTTP, target="http://a.com")
        b = Monitor(name="paused-1", type=MonitorType.HTTP, target="http://b.com", status=MonitorStatus.PAUSED)
        await store.save_monitor(a)
        await store.save_monitor(b)
        active = await store.list_active()
        assert len(active) == 1
        assert active[0].id == a.id

    @pytest.mark.asyncio
    async def test_update_status(self, store: MonitorStore, monitor: Monitor):
        await store.save_monitor(monitor)
        await store.update_status(monitor.id, MonitorStatus.PAUSED)
        loaded = await store.load_monitor(monitor.id)
        assert loaded is not None
        assert loaded.status == MonitorStatus.PAUSED

    @pytest.mark.asyncio
    async def test_delete(self, store: MonitorStore, monitor: Monitor):
        await store.save_monitor(monitor)
        await store.delete_monitor(monitor.id)
        loaded = await store.load_monitor(monitor.id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_and_get_checks(self, store: MonitorStore, monitor: Monitor):
        await store.save_monitor(monitor)
        c = MonitorCheck(monitor_id=monitor.id, status="up", result={"status_code": 200})
        await store.save_check(c)
        checks = await store.get_checks(monitor.id)
        assert len(checks) == 1
        assert checks[0].status == "up"
        assert checks[0].result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_list_monitors_by_user(self, store: MonitorStore):
        a = Monitor(name="user1-mon", type=MonitorType.HTTP, target="http://a.com", user_id="u1")
        b = Monitor(name="user2-mon", type=MonitorType.HTTP, target="http://b.com", user_id="u2")
        await store.save_monitor(a)
        await store.save_monitor(b)
        u1_list = await store.list_monitors(user_id="u1")
        assert len(u1_list) == 1
        assert u1_list[0].user_id == "u1"


class TestConditionEvaluator:
    def test_gt(self):
        e = ConditionEvaluator()
        c = Condition(metric="price", operator=ConditionOperator.GT, value="100")
        assert e.evaluate(c, {"price": 150}) is True
        assert e.evaluate(c, {"price": 50}) is False

    def test_lt(self):
        e = ConditionEvaluator()
        c = Condition(metric="temp", operator=ConditionOperator.LT, value="30")
        assert e.evaluate(c, {"temp": 25}) is True
        assert e.evaluate(c, {"temp": 35}) is False

    def test_eq(self):
        e = ConditionEvaluator()
        c = Condition(metric="status", operator=ConditionOperator.EQ, value="up")
        assert e.evaluate(c, {"status": "up"}) is True
        assert e.evaluate(c, {"status": "down"}) is False

    def test_ne(self):
        e = ConditionEvaluator()
        c = Condition(metric="status", operator=ConditionOperator.NE, value="down")
        assert e.evaluate(c, {"status": "up"}) is True
        assert e.evaluate(c, {"status": "down"}) is False

    def test_contains(self):
        e = ConditionEvaluator()
        c = Condition(metric="text", operator=ConditionOperator.CONTAINS, value="error")
        assert e.evaluate(c, {"text": "connection error occurred"}) is True
        assert e.evaluate(c, {"text": "all good"}) is False

    def test_matches(self):
        e = ConditionEvaluator()
        c = Condition(metric="log", operator=ConditionOperator.MATCHES, value="err\\d+")
        assert e.evaluate(c, {"log": "err123"}) is True
        assert e.evaluate(c, {"log": "no error"}) is False

    def test_changed(self):
        e = ConditionEvaluator()
        c = Condition(metric="content", operator=ConditionOperator.CHANGED, value=None)
        assert e.evaluate(c, {"content": "abc", "changed": True}) is True
        assert e.evaluate(c, {"content": "abc", "changed": False}) is False

    def test_missing_metric(self):
        e = ConditionEvaluator()
        c = Condition(metric="missing", operator=ConditionOperator.EQ, value="x")
        assert e.evaluate(c, {"other": "y"}) is False

    def test_check_all_no_conditions(self):
        e = ConditionEvaluator()
        assert e.check_all([], {"price": 100}) is False

    def test_check_all_all_match(self):
        e = ConditionEvaluator()
        cs = [
            Condition(metric="price", operator=ConditionOperator.GT, value="50"),
            Condition(metric="status", operator=ConditionOperator.EQ, value="up"),
        ]
        assert e.check_all(cs, {"price": 100, "status": "up"}) is True

    def test_check_all_one_fails(self):
        e = ConditionEvaluator()
        cs = [
            Condition(metric="price", operator=ConditionOperator.GT, value="50"),
            Condition(metric="status", operator=ConditionOperator.EQ, value="up"),
        ]
        assert e.check_all(cs, {"price": 10, "status": "up"}) is False


class TestMonitorEngine:
    async def test_start_stop(self, store: MonitorStore):
        engine = MonitorEngine(store)
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    async def test_add_and_run_monitor(self, store: MonitorStore):
        handler = AsyncMock(return_value={"status_code": 200})
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        await engine.start()

        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com", interval_seconds=3600)
        await engine.add_monitor(m)
        await asyncio.sleep(0.05)

        assert m.id in engine._tasks
        await engine.stop()

    async def test_pause_resume(self, store: MonitorStore):
        handler = AsyncMock(return_value={"status_code": 200})
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        await engine.start()

        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        await engine.add_monitor(m)
        assert m.id in engine._tasks

        paused = await engine.pause_monitor(m.id)
        assert paused is True
        assert m.id not in engine._tasks
        loaded = await store.load_monitor(m.id)
        assert loaded is not None
        assert loaded.status == MonitorStatus.PAUSED

        resumed = await engine.resume_monitor(m.id)
        assert resumed is True
        assert m.id in engine._tasks
        await engine.stop()

    async def test_remove_monitor(self, store: MonitorStore):
        handler = AsyncMock(return_value={"status_code": 200})
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        await engine.start()

        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        await engine.add_monitor(m)
        assert m.id in engine._tasks

        await engine.remove_monitor(m.id)
        loaded = await store.load_monitor(m.id)
        assert loaded is None
        await engine.stop()

    async def test_list_monitors(self, store: MonitorStore):
        engine = MonitorEngine(store)
        m1 = Monitor(name="a", type=MonitorType.HTTP, target="http://a.com", user_id="u1")
        m2 = Monitor(name="b", type=MonitorType.HTTP, target="http://b.com", user_id="u2")
        await store.save_monitor(m1)
        await store.save_monitor(m2)

        all_m = await engine.list_monitors()
        assert len(all_m) == 2

        u1_m = await engine.list_monitors(user_id="u1")
        assert len(u1_m) == 1
        assert u1_m[0].id == m1.id


class TestAlertDispatcher:
    async def test_dispatch_logs(self):
        d = AlertDispatcher()
        m = Monitor(name="test", type=MonitorType.HTTP, target="http://example.com")
        c = MonitorCheck(monitor_id=m.id, status="up")
        await d.dispatch(m, c, "test alert")


class TestCheckNow:
    async def test_check_now_returns_none_when_ok(self, store: MonitorStore):
        handler = AsyncMock(return_value=None)
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        await store.save_monitor(m)
        result = await engine.check_now(m.id)
        assert result is None

    async def test_check_now_returns_alert_when_triggered(self, store: MonitorStore):
        handler = AsyncMock(return_value="🔴 Something went wrong")
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        await store.save_monitor(m)
        result = await engine.check_now(m.id)
        assert result == "🔴 Something went wrong"

    async def test_check_now_nonexistent_monitor(self, store: MonitorStore):
        engine = MonitorEngine(store)
        result = await engine.check_now("nonexistent")
        assert result is None

    async def test_check_now_records_check(self, store: MonitorStore):
        handler = AsyncMock(return_value="alert text")
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        await store.save_monitor(m)
        await engine.check_now(m.id)
        checks = await store.get_checks(m.id)
        assert len(checks) == 1
        assert checks[0].triggered is True


class TestCooldown:
    async def test_cooldown_suppresses_notification(self, store: MonitorStore):
        sent: list[str] = []

        async def send_fn(channel: str, text: str):
            sent.append(f"{channel}:{text}")

        engine = MonitorEngine(store, send_fn=send_fn)
        handler = AsyncMock(return_value="alert")
        engine.register_handler("http", handler)
        m = Monitor(
            name="test", type=MonitorType.HTTP, target="https://example.com", cooldown_minutes=60, channel="test_ch"
        )
        await store.save_monitor(m)
        await engine.check_now(m.id)
        first_count = len(sent)
        await engine.check_now(m.id)
        assert len(sent) == first_count

    async def test_no_cooldown_allows_notification(self, store: MonitorStore):
        sent: list[str] = []

        async def send_fn(channel: str, text: str):
            sent.append(f"{channel}:{text}")

        engine = MonitorEngine(store, send_fn=send_fn)
        handler = AsyncMock(return_value="alert")
        engine.register_handler("http", handler)
        m = Monitor(
            name="test", type=MonitorType.HTTP, target="https://example.com", cooldown_minutes=0, channel="test_ch"
        )
        await store.save_monitor(m)
        await engine.check_now(m.id)
        assert len(sent) >= 1

    async def test_cooldown_measured_from_last_alert(self, store: MonitorStore):
        sent: list[str] = []

        async def send_fn(channel: str, text: str):
            sent.append(f"{channel}:{text}")

        engine = MonitorEngine(store, send_fn=send_fn)
        handler = AsyncMock(return_value="alert")
        engine.register_handler("http", handler)
        m = Monitor(
            name="test", type=MonitorType.HTTP, target="https://example.com", cooldown_minutes=30, channel="test_ch"
        )
        await store.save_monitor(m)
        await engine.check_now(m.id)
        assert len(sent) == 1
        engine._last_alert_at[m.id] = time.time() - 3600
        await engine.check_now(m.id)
        assert len(sent) == 2, "alert must fire again once cooldown elapsed"

    async def test_cooldown_initialized_from_last_triggered(self, store: MonitorStore):
        sent: list[str] = []

        async def send_fn(channel: str, text: str):
            sent.append(f"{channel}:{text}")

        engine = MonitorEngine(store, send_fn=send_fn)
        handler = AsyncMock(return_value="alert")
        engine.register_handler("http", handler)
        m = Monitor(
            name="test", type=MonitorType.HTTP, target="https://example.com", cooldown_minutes=30, channel="test_ch"
        )
        m.last_check = CheckResult(
            status="down",
            checked_at=time.time() - 60,
            response_time_ms=5,
            triggered=True,
            error=None,
        )
        engine._init_alert_clock(m)
        await store.save_monitor(m)
        await engine.check_now(m.id)
        assert len(sent) == 0, "cooldown must count from previous triggered check"

    async def test_alert_delivery_failure_does_not_raise(self, store: MonitorStore):
        async def boom_send(channel: str, text: str):
            raise RuntimeError("channel dead")

        engine = MonitorEngine(store, send_fn=boom_send)
        handler = AsyncMock(return_value="alert")
        engine.register_handler("http", handler)
        m = Monitor(
            name="test", type=MonitorType.HTTP, target="https://example.com", cooldown_minutes=0, channel="test_ch"
        )
        await store.save_monitor(m)
        result = await engine.check_now(m.id)
        assert result == "alert"


class TestCheckerSignatures:
    async def test_price_checker_returns_str_or_none(self):
        from raven.core.monitor.checkers.price import check_price

        m = Monitor(name="test-price", type=MonitorType.PRICE, target="nonexistentcoinxyz")
        result = await check_price(m)
        assert result is None or isinstance(result, str)

    async def test_price_checker_reports_failure(self, monkeypatch):
        from raven.core.monitor.checkers import price

        async def boom(url, headers=None, timeout=15.0):
            raise RuntimeError("coingecko down")

        monkeypatch.setattr("raven.core.monitor.checkers.price.client_manager.get", boom)
        m = Monitor(name="test-price", type=MonitorType.PRICE, target="btc")
        result = await price.check_price(m)
        assert isinstance(result, str)
        assert "failed" in result.lower()

    async def test_price_checker_reports_unknown_coin(self, monkeypatch):
        from raven.core.monitor.checkers import price

        async def empty(url, headers=None, timeout=15.0):
            return {}

        monkeypatch.setattr("raven.core.monitor.checkers.price.client_manager.get", empty)
        m = Monitor(name="test-price", type=MonitorType.PRICE, target="notacoin")
        result = await price.check_price(m)
        assert isinstance(result, str)
        assert "not found" in result

    async def test_http_checker_returns_str_or_none(self):
        from raven.core.monitor.checkers.http_check import check_http

        m = Monitor(name="test-http", type=MonitorType.HTTP, target="https://invalid.example.test")
        try:
            result = await check_http(m)
        except Exception:
            result = None
        assert result is None or isinstance(result, str)

    async def test_rss_checker_returns_str_or_none(self):
        from raven.core.monitor.checkers.rss import check_rss

        m = Monitor(name="test-rss", type=MonitorType.RSS, target="https://invalid.example.test/rss")
        try:
            result = await check_rss(m)
        except Exception:
            result = None
        assert result is None or isinstance(result, str)

    async def test_rss_checker_parses_xml_feed(self, monkeypatch):
        import httpx

        from raven.core.monitor.checkers import rss

        xml = (
            '<?xml version="1.0"?><rss version="2.0"><channel><item>'
            "<title>New post</title><link>https://example.com/1</link><guid>g1</guid>"
            "</item></channel></rss>"
        )

        class _Resp:
            text = xml

        async def fake_request(method: str, url: str, **kwargs) -> httpx.Response:
            return _Resp()  # type: ignore[return-value]

        monkeypatch.setattr("raven.core.monitor.checkers.rss.client_manager.request", fake_request)
        m = Monitor(id="m1", name="test-rss", type=MonitorType.RSS, target="https://example.com/feed.xml")
        result = await rss.check_rss(m)
        assert isinstance(result, str)
        assert "New post" in result

        result_again = await rss.check_rss(m)
        assert result_again is None, "same entry must not alert twice"


class TestEngineFromDb:
    def test_engine_from_db_creates_store(self, db_path: str):
        engine = MonitorEngine.from_db(db_path)
        assert engine._store is not None

    def test_engine_with_path_creates_store(self, db_path: str):
        from pathlib import Path

        engine = MonitorEngine(Path(db_path))
        assert engine._store is not None

    async def test_legacy_db_migrated(self, db_path: str):
        import aiosqlite

        conn = await aiosqlite.connect(db_path)
        await conn.execute(
            """CREATE TABLE monitors (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}', condition TEXT NOT NULL DEFAULT '',
                cooldown_minutes INTEGER NOT NULL DEFAULT 30, interval_seconds INTEGER NOT NULL DEFAULT 300,
                notify_channels TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active',
                user_id TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '',
                last_checked TEXT, last_triggered TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        await conn.execute(
            """CREATE TABLE monitor_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, monitor_id TEXT NOT NULL,
                status TEXT NOT NULL, checked_at REAL NOT NULL, response_time_ms REAL,
                triggered INTEGER DEFAULT 0, result TEXT, error TEXT
            )"""
        )
        await conn.commit()
        await conn.close()

        s = MonitorStore(db_path)
        m = Monitor(name="mig", type=MonitorType.HTTP, target="https://x", group="prod", slo_target=0.95)
        await s.save_monitor(m)
        loaded = await s.load_monitor(m.id)
        assert loaded is not None
        assert loaded.group == "prod"
        assert loaded.slo_target == 0.95
        assert loaded.slo_window_seconds == 86400
        await s.close()


class TestSLOStats:
    def test_slo_stats_empty(self):
        s = SLOStats(target=0.99, window_seconds=86400, total_checks=0, ok_checks=0, fail_checks=0)
        assert s.success_rate == 1.0
        assert s.error_budget_remaining == 1.0

    def test_slo_stats_compute(self):
        s = SLOStats(target=0.99, window_seconds=86400, total_checks=100, ok_checks=95, fail_checks=5)
        assert s.success_rate == 0.95
        assert s.ok_checks == 95
        assert s.fail_checks == 5

    def test_slo_stats_dict(self):
        s = SLOStats(target=0.9, window_seconds=86400, total_checks=10, ok_checks=9, fail_checks=1)
        d = s.to_dict()
        assert d["target"] == 0.9
        assert d["success_rate"] == 0.9
        assert d["error_budget_remaining"] == 0.0

    async def test_get_slo_stats_filters_window(self, store: MonitorStore):
        m = Monitor(name="slo", type=MonitorType.HTTP, target="https://example.com")
        await store.save_monitor(m)
        now = time.time()
        await store.save_check(
            MonitorCheck(monitor_id=m.id, status="up", checked_at=now - 10, triggered=False)
        )
        await store.save_check(
            MonitorCheck(monitor_id=m.id, status="down", checked_at=now - 50, triggered=True)
        )
        await store.save_check(
            MonitorCheck(monitor_id=m.id, status="down", checked_at=now - 2000, triggered=True)
        )
        stats = await store.get_slo_stats(m.id, 1000)
        assert stats == {"total": 2, "ok": 1, "fail": 1}


class TestAdaptiveInterval:
    async def test_interval_doubles_after_threshold_failures(self, store: MonitorStore):
        handler = AsyncMock(return_value="alert")
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="t", type=MonitorType.HTTP, target="https://example.com", interval_seconds=60)
        await store.save_monitor(m)
        assert engine.effective_interval(m.id, 60) == 60
        for _ in range(3):
            await engine.check_now(m.id)
        assert engine.effective_interval(m.id, 60) == 120
        assert engine._get_interval(m) == 120

    async def test_interval_restored_after_successes(self, store: MonitorStore):
        handler = AsyncMock(side_effect=["alert"] * 3 + [None] * 3)
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="t", type=MonitorType.HTTP, target="https://example.com", interval_seconds=60)
        await store.save_monitor(m)
        for _ in range(3):
            await engine.check_now(m.id)
        assert engine.effective_interval(m.id, 60) == 120
        for _ in range(3):
            await engine.check_now(m.id)
        assert engine.effective_interval(m.id, 60) == 60

    async def test_interval_capped(self, store: MonitorStore):
        handler = AsyncMock(return_value="alert")
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(name="t", type=MonitorType.HTTP, target="https://example.com", interval_seconds=1000)
        await store.save_monitor(m)
        for _ in range(3):
            await engine.check_now(m.id)
        assert engine.effective_interval(m.id, 1000) == 2000
        for _ in range(3):
            await engine.check_now(m.id)
        assert engine.effective_interval(m.id, 1000) == 3600

    async def test_get_slo_report(self, store: MonitorStore):
        handler = AsyncMock(return_value="alert")
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        m = Monitor(
            name="t",
            type=MonitorType.HTTP,
            target="https://example.com",
            interval_seconds=60,
            group="prod",
        )
        await store.save_monitor(m)
        await engine.check_now(m.id)
        report = await engine.slo_report()
        assert len(report) == 1
        assert report[0]["monitor_id"] == m.id
        assert report[0]["group"] == "prod"
        assert report[0]["total_checks"] == 1
        assert report[0]["success_rate"] == 0.0
        assert report[0]["slo_breached"] is True


class TestAlertDispatcherStreak:
    async def test_suppresses_below_threshold(self):
        d = AlertDispatcher(min_consecutive=3)
        m = Monitor(name="t", type=MonitorType.HTTP, target="x", group="prod")
        check = MonitorCheck(monitor_id="x", status="down", triggered=True)
        await d.dispatch(m, check, "down")
        assert d.streak(m, check) == 1

    async def test_fires_after_threshold(self):
        d = AlertDispatcher(min_consecutive=3)
        m = Monitor(name="t", type=MonitorType.HTTP, target="x", group="prod")
        c1 = MonitorCheck(monitor_id="x", status="down", triggered=True)
        await d.dispatch(m, c1, "down")
        await d.dispatch(m, c1, "down")
        await d.dispatch(m, c1, "down")
        assert d.streak(m, c1) == 0

    async def test_up_resets_streak(self):
        d = AlertDispatcher(min_consecutive=3)
        m = Monitor(name="t", type=MonitorType.HTTP, target="x", group="prod")
        down = MonitorCheck(monitor_id="x", status="down", triggered=True)
        up = MonitorCheck(monitor_id="x", status="up", triggered=False)
        await d.dispatch(m, down, "down")
        await d.dispatch(m, up, "up")
        assert d.streak(m, down) == 0

    async def test_group_isolated_streaks(self):
        d = AlertDispatcher(min_consecutive=3)
        m1 = Monitor(name="a", type=MonitorType.HTTP, target="x", group="prod")
        m2 = Monitor(name="b", type=MonitorType.HTTP, target="x", group="dev")
        check = MonitorCheck(monitor_id="x", status="down", triggered=True)
        await d.dispatch(m1, check, "down")
        assert d.streak(m1, check) == 1
        assert d.streak(m2, check) == 0
