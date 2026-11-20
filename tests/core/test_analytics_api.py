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
    """The endpoints forward, and what they forward is the shape `/analytics` reads.

    `test_analytics_metric_names.py` drives these handlers over a real engine; the mocks here carry
    production-shaped payloads so a future edit to one of them is compared against something the browser
    actually consumes.
    """

    @pytest.fixture
    def client(self):
        app = FastAPI()
        engine = MagicMock()
        point = {"ts": 123, "avg": 42.0, "max": 42.0, "min": 42.0, "count": 1}
        engine.query_metrics_list = AsyncMock(return_value=["metric1", "metric2"])
        engine.query_series = AsyncMock(return_value=[point])
        engine.query_summary = AsyncMock(
            return_value={"metrics": [{"name": "metric1", "avg": 42.0, "max": 42.0, "samples": 1}], "total_data_points": 1}
        )
        engine.query_aggregated = AsyncMock(
            return_value={"received": 500, "errors": 0, "error_rate": 0, "message_series": [point], "error_series": []}
        )
        engine.query_tool_usage = AsyncMock(
            return_value=[{"name": "bash", "category": "exec", "total": 10, "series": [point]}]
        )
        engine.query_tool_breakdown = AsyncMock(
            return_value={"success": 9, "errors": 1, "total": 10, "success_series": [point], "error_series": []}
        )
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
        assert response.json()["total_data_points"] == 1

    def test_get_summary_with_since(self, client):
        response = client.get("/api/analytics/summary?since=1000000")
        assert response.status_code == 200

    def test_get_aggregated(self, client):
        response = client.get("/api/analytics/aggregated")
        assert response.status_code == 200
        assert response.json()["received"] == 500

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
