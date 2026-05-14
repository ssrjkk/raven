from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.monitor.alert import AlertDispatcher
from raven.core.monitor.conditions import ConditionEvaluator
from raven.core.monitor.engine import MonitorEngine
from raven.core.monitor.models import (
    Condition,
    ConditionOperator,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    MonitorType,
)
from raven.core.monitor.store import MonitorStore


@pytest.fixture(autouse=True)
def _clear_cache():
    import raven.core.monitor.store as ms
    ms._local.conn = None


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "monitors.db")


@pytest.fixture
def store(db_path: str) -> MonitorStore:
    return MonitorStore(db_path)


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
    def test_save_and_load(self, store: MonitorStore, monitor: Monitor):
        store.save_monitor(monitor)
        loaded = store.load_monitor(monitor.id)
        assert loaded is not None
        assert loaded.name == "test-http"
        assert loaded.type == MonitorType.HTTP
        assert loaded.target == "https://example.com"

    def test_save_and_load_with_conditions(self, store: MonitorStore):
        m = Monitor(
            name="price-check",
            type=MonitorType.PRICE,
            target="bitcoin",
            conditions=[Condition(metric="price", operator=ConditionOperator.GT, value="50000")],
        )
        store.save_monitor(m)
        loaded = store.load_monitor(m.id)
        assert loaded is not None
        assert len(loaded.conditions) == 1
        assert loaded.conditions[0].metric == "price"
        assert loaded.conditions[0].operator == ConditionOperator.GT

    def test_list_active(self, store: MonitorStore):
        a = Monitor(name="active-1", type=MonitorType.HTTP, target="http://a.com")
        b = Monitor(name="paused-1", type=MonitorType.HTTP, target="http://b.com", status=MonitorStatus.PAUSED)
        store.save_monitor(a)
        store.save_monitor(b)
        active = store.list_active()
        assert len(active) == 1
        assert active[0].id == a.id

    def test_update_status(self, store: MonitorStore, monitor: Monitor):
        store.save_monitor(monitor)
        store.update_status(monitor.id, MonitorStatus.PAUSED)
        loaded = store.load_monitor(monitor.id)
        assert loaded is not None
        assert loaded.status == MonitorStatus.PAUSED

    def test_delete(self, store: MonitorStore, monitor: Monitor):
        store.save_monitor(monitor)
        store.delete_monitor(monitor.id)
        assert store.load_monitor(monitor.id) is None

    def test_save_and_get_checks(self, store: MonitorStore, monitor: Monitor):
        store.save_monitor(monitor)
        c = MonitorCheck(monitor_id=monitor.id, status="up", result={"status_code": 200})
        store.save_check(c)
        checks = store.get_checks(monitor.id)
        assert len(checks) == 1
        assert checks[0].status == "up"
        assert checks[0].result["status_code"] == 200

    def test_list_monitors_by_user(self, store: MonitorStore):
        a = Monitor(name="user1-mon", type=MonitorType.HTTP, target="http://a.com", user_id="u1")
        b = Monitor(name="user2-mon", type=MonitorType.HTTP, target="http://b.com", user_id="u2")
        store.save_monitor(a)
        store.save_monitor(b)
        u1_list = store.list_monitors(user_id="u1")
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
        engine.add_monitor(m)
        await asyncio.sleep(0.05)

        assert m.id in engine._tasks
        await engine.stop()

    async def test_pause_resume(self, store: MonitorStore):
        handler = AsyncMock(return_value={"status_code": 200})
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        await engine.start()

        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        engine.add_monitor(m)
        assert m.id in engine._tasks

        paused = engine.pause_monitor(m.id)
        assert paused is True
        assert m.id not in engine._tasks
        loaded = store.load_monitor(m.id)
        assert loaded is not None
        assert loaded.status == MonitorStatus.PAUSED

        resumed = engine.resume_monitor(m.id)
        assert resumed is True
        assert m.id in engine._tasks
        await engine.stop()

    async def test_remove_monitor(self, store: MonitorStore):
        handler = AsyncMock(return_value={"status_code": 200})
        engine = MonitorEngine(store)
        engine.register_handler("http", handler)
        await engine.start()

        m = Monitor(name="test", type=MonitorType.HTTP, target="https://example.com")
        engine.add_monitor(m)
        assert m.id in engine._tasks

        engine.remove_monitor(m.id)
        assert store.load_monitor(m.id) is None
        await engine.stop()

    async def test_list_monitors(self, store: MonitorStore):
        engine = MonitorEngine(store)
        m1 = Monitor(name="a", type=MonitorType.HTTP, target="http://a.com", user_id="u1")
        m2 = Monitor(name="b", type=MonitorType.HTTP, target="http://b.com", user_id="u2")
        store.save_monitor(m1)
        store.save_monitor(m2)

        all_m = engine.list_monitors()
        assert len(all_m) == 2

        u1_m = engine.list_monitors(user_id="u1")
        assert len(u1_m) == 1
        assert u1_m[0].id == m1.id


class TestAlertDispatcher:
    async def test_dispatch_logs(self):
        d = AlertDispatcher()
        m = Monitor(name="test", type=MonitorType.HTTP, target="http://example.com")
        c = MonitorCheck(monitor_id=m.id, status="up")
        await d.dispatch(m, c, "test alert")
