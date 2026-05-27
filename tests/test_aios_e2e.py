"""End-to-end test for the AIOS FastAPI gateway via TestClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aios.api.bridge import router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestAiosGatewayE2E:
    def test_health_endpoint(self, client):
        resp = client.get("/aios/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch("aios.api.bridge._client")
    def test_ai_endpoint(self, mock_client, client):
        from ravencode.api.client import AIResponse
        mock_client.ask = AsyncMock(return_value=AIResponse(text="hello world", model="gpt4", provider="openai"))

        resp = client.post("/aios/ai", json={"prompt": "hi", "task": "code"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "hello world"
        assert data["provider"] == "openai"

    @patch("aios.api.bridge._client")
    def test_ai_endpoint_degraded(self, mock_client, client):
        from ravencode.api.client import AIResponse
        mock_client.ask = AsyncMock(return_value=AIResponse(text="unavailable", model="none", provider="none"))

        resp = client.post("/aios/ai", json={"prompt": "hi", "task": "code"})
        assert resp.status_code == 200
        assert resp.json()["provider"] == "none"

    def test_exec_endpoint_no_auth(self, client):
        resp = client.post("/aios/exec", json={"command": "echo test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "test" in data["output"]
