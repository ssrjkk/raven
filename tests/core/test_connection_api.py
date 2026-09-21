from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.connection_api import _is_masked, _mask_key, create_connection_router


@pytest.fixture()
def mock_store():
    import asyncio
    store = MagicMock()
    store._data = {
        "providers": [
            {
                "name": "test-provider",
                "type": "openai",
                "api_key": "sk-test-1234567890",
                "base_url": "",
                "model": "gpt-4",
                "enabled": True,
                "extra": {},
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }
        ],
        "contexts": [
            {
                "id": "ctx-1",
                "name": "Test Context",
                "provider": "test-provider",
                "repositories": [],
                "files": [],
                "folders": [],
                "filters": "",
                "description": "",
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }
        ],
        "agents": [
            {
                "id": "ag-1",
                "name": "Test Agent",
                "provider": "test-provider",
                "context": "ctx-1",
                "model": "gpt-4",
                "system_prompt": "",
                "enabled": True,
                "history": [],
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }
        ],
    }
    store._lock = asyncio.Lock()

    async def _mutate(fn):
        async with store._lock:
            return fn()

    store.mutate = _mutate
    return store


@pytest.fixture()
def client(mock_store):
    import raven.core.connection_api as conn_mod
    original_store = conn_mod._store
    conn_mod._store = mock_store
    try:
        router = create_connection_router()
        app = FastAPI()

        @app.middleware("http")
        async def add_admin_role(request, call_next):
            request.state.user_role = "admin"
            return await call_next(request)

        app.include_router(router)
        yield TestClient(app)
    finally:
        conn_mod._store = original_store


class TestHelpers:
    def test_mask_key_long(self):
        assert _mask_key("sk-test-1234567890") == "sk-t...7890"

    def test_mask_key_short(self):
        assert _mask_key("short") == "*****"

    def test_mask_key_empty(self):
        assert _mask_key("") == ""

    def test_is_masked_with_dots(self):
        assert _is_masked("sk-t...7890") is True

    def test_is_masked_all_stars(self):
        assert _is_masked("********") is True

    def test_is_masked_normal(self):
        assert _is_masked("sk-test-key") is False


class TestProviders:
    def test_list_providers(self, client):
        resp = client.get("/api/connections/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["providers"]) == 1
        assert data["providers"][0]["name"] == "test-provider"

    def test_get_provider(self, client):
        resp = client.get("/api/connections/providers/test-provider")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-provider"

    def test_get_provider_not_found(self, client):
        resp = client.get("/api/connections/providers/missing")
        assert resp.status_code == 404


class TestContexts:
    def test_list_contexts(self, client):
        resp = client.get("/api/connections/contexts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 1

    def test_create_context(self, client, mock_store):
        resp = client.post("/api/connections/contexts", json={
            "name": "New Context",
            "provider": "",
            "repositories": [],
            "files": [],
            "folders": [],
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Context"


class TestAgents:
    def test_list_agents(self, client):
        resp = client.get("/api/connections/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1

    def test_create_agent(self, client):
        resp = client.post("/api/connections/agents", json={
            "name": "New Agent",
            "provider": "",
            "context": "",
            "model": "gpt-4",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Agent"
