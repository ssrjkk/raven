from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from raven.core.auth.auth_handler import auth_handler
from raven.gateway.daemon import RavenFlowDaemon


@pytest.fixture
def auth_headers():
    token = auth_handler.create_token("testuser", "admin")
    return {"Authorization": f"Bearer {token}"}


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

    def test_health_endpoint_no_auth(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_list_tools_requires_auth(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/tools")
            assert resp.status_code == 401

    def test_list_tools_endpoint(self, auth_headers):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/tools", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "tools" in data
            assert isinstance(data["tools"], list)

    def test_list_sessions_requires_auth(self):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/sessions")
            assert resp.status_code == 401

    def test_list_sessions_empty(self, auth_headers):
        d = RavenFlowDaemon(port=18789)
        with TestClient(d.app) as client:
            resp = client.get("/api/sessions", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "sessions" in data
