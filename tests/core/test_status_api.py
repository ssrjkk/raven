from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from raven.core.status_api import create_status_router


@pytest.fixture()
def mock_gateway() -> MagicMock:
    gw = MagicMock()
    gw.channels = MagicMock()
    gw.channels.list_ids = AsyncMock(return_value=["ch1", "ch2"])
    gw.registry = MagicMock()
    gw.registry.list_agents.return_value = ["agent1", "agent2"]
    gw.registry.create_agent = MagicMock()
    gw.db = MagicMock()
    gw.db.get_or_create_session = AsyncMock(return_value=MagicMock())
    return gw


@pytest.fixture()
def mock_plugin_loader() -> MagicMock:
    pl = MagicMock()
    pl.tools = [MagicMock(), MagicMock(), MagicMock()]
    return pl


@pytest.fixture()
def client(mock_gateway: MagicMock, mock_plugin_loader: MagicMock) -> TestClient:
    import asyncio

    from fastapi import FastAPI

    stop_event = asyncio.Event()
    app = FastAPI()
    app.include_router(create_status_router(mock_gateway, mock_plugin_loader, stop_event))
    return TestClient(app)


def test_api_status(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert "channels" in data
    assert data["plugins"] == 3


def test_api_agents(client: TestClient) -> None:
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data == ["agent1", "agent2"]


def test_api_health(client: TestClient) -> None:
    with patch("raven.core.status_api.health") as mock_health:
        mock_health.check_all = AsyncMock(return_value={"status": "healthy"})
        resp = client.get("/api/health")
        assert resp.status_code == 200


def test_api_ready(client: TestClient) -> None:
    with patch("raven.core.status_api.health") as mock_health:
        mock_health.check_readiness = AsyncMock(return_value={"ready": True})
        resp = client.get("/api/health/ready")
        assert resp.status_code == 200


def test_api_live(client: TestClient) -> None:
    resp = client.get("/api/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_metrics(client: TestClient) -> None:
    with patch("raven.core.status_api.metrics") as mock_metrics:
        mock_metrics.snapshot.return_value = {"requests": 100}
        resp = client.get("/api/metrics")
        assert resp.status_code == 200


def test_api_metrics_prometheus(client: TestClient) -> None:
    with patch("raven.core.status_api.metrics") as mock_metrics:
        mock_metrics.prometheus.return_value = "# HELP requests\nrequests 100"
        resp = client.get("/api/metrics/prometheus")
        assert resp.status_code == 200
        assert "requests" in resp.text


def test_api_shutdown(client: TestClient, mock_gateway: MagicMock, mock_plugin_loader: MagicMock) -> None:
    import asyncio

    from fastapi import FastAPI

    stop_event = asyncio.Event()
    app = FastAPI()
    app.include_router(create_status_router(mock_gateway, mock_plugin_loader, stop_event))
    tc = TestClient(app)

    with patch("raven.core.status_api.audit_logger") as mock_audit:
        mock_audit.sensitive = AsyncMock()
        resp = tc.post("/api/shutdown")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    assert stop_event.is_set()


def test_api_set_agent(client: TestClient) -> None:
    resp = client.post("/api/sessions/sess1/agent", json={"agent_id": "coder"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "coder"
    assert data["session_id"] == "sess1"
