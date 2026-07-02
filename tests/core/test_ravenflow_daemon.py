from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from raven.gateway.daemon import RavenFlowDaemon


class TestRavenFlowDaemon:
    def test_daemon_init(self):
        d = RavenFlowDaemon(port=18789)
        assert d.port == 18789
        assert "RavenFlow" in d.app.title

    def test_health_endpoint(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data

    def test_list_tools_endpoint(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/tools")
            assert resp.status_code == 200
            data = resp.json()
            assert "tools" in data
            assert isinstance(data["tools"], list)

    def test_list_sessions_empty(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert "sessions" in data
