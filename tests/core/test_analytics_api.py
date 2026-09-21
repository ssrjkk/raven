from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.analytics_api import (
    _get_engine,
    create_analytics_router,
    set_analytics_engine,
)


class TestAnalyticsEngineSetup:
    def test_get_engine_raises_when_not_initialized(self):
        import raven.core.analytics_api as mod

        original = mod._engine
        try:
            mod._engine = None
            with pytest.raises(RuntimeError, match="not initialized"):
                _get_engine()
        finally:
            mod._engine = original

    def test_set_and_get_engine(self):
        import raven.core.analytics_api as mod

        original = mod._engine
        try:
            engine = MagicMock()
            set_analytics_engine(engine)
            assert _get_engine() is engine
        finally:
            mod._engine = original


class TestAnalyticsRouter:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        engine = MagicMock()
        engine.query_metrics_list = AsyncMock(return_value=["metric1", "metric2"])
        engine.query_series = AsyncMock(return_value=[{"ts": 123, "value": 42}])
        engine.query_summary = AsyncMock(return_value={"total": 100})
        engine.query_aggregated = AsyncMock(return_value={"sum": 500})
        engine.query_tool_usage = AsyncMock(return_value={"bash": 10, "read": 5})
        engine.query_tool_breakdown = AsyncMock(return_value=[{"tool": "bash", "count": 10}])
        set_analytics_engine(engine)
        app.include_router(create_analytics_router())
        return TestClient(app)

    def test_list_metrics(self, client):
        response = client.get("/api/analytics/metrics")
        assert response.status_code == 200
        assert response.json() == {"metrics": ["metric1", "metric2"]}

    def test_get_series(self, client):
        response = client.get("/api/analytics/series/cpu_usage?bucket=5m")
        assert response.status_code == 200
        data = response.json()
        assert data["metric"] == "cpu_usage"
        assert "data" in data

    def test_get_series_with_since(self, client):
        response = client.get("/api/analytics/series/cpu_usage?since=1000000&bucket=1h")
        assert response.status_code == 200

    def test_get_summary(self, client):
        response = client.get("/api/analytics/summary")
        assert response.status_code == 200
        assert response.json() == {"total": 100}

    def test_get_summary_with_since(self, client):
        response = client.get("/api/analytics/summary?since=1000000")
        assert response.status_code == 200

    def test_get_aggregated(self, client):
        response = client.get("/api/analytics/aggregated")
        assert response.status_code == 200
        assert response.json() == {"sum": 500}

    def test_get_overview(self, client):
        response = client.get("/api/analytics/overview")
        assert response.status_code == 200
        data = response.json()
        assert "last_hour" in data
        assert "last_24h" in data

    def test_get_tool_usage(self, client):
        response = client.get("/api/analytics/tools/usage")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data

    def test_get_tool_breakdown(self, client):
        response = client.get("/api/analytics/tools/breakdown")
        assert response.status_code == 200

    def test_get_full_overview(self, client):
        response = client.get("/api/analytics/full")
        assert response.status_code == 200
        data = response.json()
        assert "last_hour" in data
        assert "last_24h" in data
        assert "summary" in data
        assert "tool_breakdown" in data
        assert "tool_usage" in data
        assert "tool_usage_1h" in data
