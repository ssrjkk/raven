from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.ops_api import create_ops_router


@pytest.fixture()
def mock_gateway():
    gw = MagicMock()
    gw.llm = MagicMock()
    return gw


@pytest.fixture()
def mock_features():
    ff = MagicMock()
    ff.is_enabled.return_value = False
    return ff


@pytest.fixture()
def mock_monitor_engine():
    eng = AsyncMock()
    eng.list_monitors = AsyncMock(return_value=[])
    eng.count_monitors = AsyncMock(return_value=0)
    eng.slo_report = AsyncMock(return_value=[])
    eng.pause_monitor = AsyncMock()
    eng.resume_monitor = AsyncMock()
    return eng


@pytest.fixture()
def mock_routine_engine():
    eng = AsyncMock()
    eng.list_routines = AsyncMock(return_value=[])
    eng._store = AsyncMock()
    eng._store.count_routines = AsyncMock(return_value=0)
    eng._store.save_routine = AsyncMock()
    eng._store.delete_routine = AsyncMock()
    eng.pause_routine = AsyncMock()
    eng.resume_routine = AsyncMock()
    return eng


@pytest.fixture()
def client(mock_gateway, mock_features, mock_monitor_engine, mock_routine_engine):
    router = create_ops_router(mock_gateway, mock_features)
    app = FastAPI()
    app.state.monitor_engine = mock_monitor_engine
    app.state.routine_engine = mock_routine_engine
    app.include_router(router)
    return TestClient(app)


class TestMonitorEndpoints:
    def test_monitor_list(self, client, mock_monitor_engine):
        mock_monitor_engine.list_monitors.return_value = []
        mock_monitor_engine.count_monitors.return_value = 0
        resp = client.get("/api/monitor/list")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_monitor_slo(self, client, mock_monitor_engine):
        mock_monitor_engine.slo_report.return_value = []
        resp = client.get("/api/monitor/slo")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_monitor_pause(self, client, mock_monitor_engine):
        resp = client.post("/api/monitor/pause/mon-123")
        assert resp.status_code == 200
        mock_monitor_engine.pause_monitor.assert_called_once_with("mon-123")

    def test_monitor_resume(self, client, mock_monitor_engine):
        resp = client.post("/api/monitor/resume/mon-123")
        assert resp.status_code == 200
        mock_monitor_engine.resume_monitor.assert_called_once_with("mon-123")


class TestRoutineEndpoints:
    def test_routine_list(self, client, mock_routine_engine):
        mock_routine_engine.list_routines.return_value = []
        mock_routine_engine._store.count_routines.return_value = 0
        resp = client.get("/api/routine/list")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_routine_create(self, client, mock_routine_engine):
        resp = client.post("/api/routine/create", json={"name": "Test", "action": "send_message"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_routine_delete(self, client, mock_routine_engine):
        resp = client.delete("/api/routine/routine-123")
        assert resp.status_code == 200
        mock_routine_engine._store.delete_routine.assert_called_once_with("routine-123")

    def test_routine_pause(self, client, mock_routine_engine):
        resp = client.post("/api/routine/pause/routine-123")
        assert resp.status_code == 200
        mock_routine_engine.pause_routine.assert_called_once_with("routine-123")

    def test_routine_resume(self, client, mock_routine_engine):
        resp = client.post("/api/routine/resume/routine-123")
        assert resp.status_code == 200
        mock_routine_engine.resume_routine.assert_called_once_with("routine-123")


class TestConnectionOwnership:
    """A store built inside a request owns the connection it opened, so it has to close it."""

    @staticmethod
    def _planner_client(mock_gateway):
        features = MagicMock()
        features.is_enabled.return_value = True
        app = FastAPI()
        app.include_router(create_ops_router(mock_gateway, features))
        return TestClient(app)

    def test_task_and_code_lists_close_every_connection_they_open(
        self, mock_gateway, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The routes build a store per request, so the sqlite backend is the thing that must be closed."""
        import itertools

        if os.environ.get("DATABASE_URL", "").startswith("postgresql"):
            pytest.skip("the postgres backend is instrumented by its own suite")

        import raven.core.asyncdb as asyncdb
        from raven.core.config import settings

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "ops.db"))
        opened: list[int] = []
        closed: list[int] = []
        seq = itertools.count()
        backend = asyncdb.SQLiteDB
        original_init = backend.__init__
        original_close = backend.close

        def _init(self, *args, **kwargs):
            self._trace = next(seq)
            opened.append(self._trace)
            return original_init(self, *args, **kwargs)

        async def _close(self):
            closed.append(getattr(self, "_trace", -1))
            return await original_close(self)

        monkeypatch.setattr(backend, "__init__", _init)
        monkeypatch.setattr(backend, "close", _close)

        client = self._planner_client(mock_gateway)
        with client:
            for _ in range(3):
                assert client.get("/api/task/list").status_code == 200
                assert client.get("/api/code/list").status_code == 200

        assert len(opened) == 6, opened
        assert closed == opened, (opened, closed)

    def test_the_two_endpoints_only_exist_with_the_planner_feature(self, mock_gateway) -> None:
        features = MagicMock()
        features.is_enabled.return_value = False
        app = FastAPI()
        app.include_router(create_ops_router(mock_gateway, features))
        with TestClient(app) as client:
            assert client.get("/api/task/list").status_code == 404
