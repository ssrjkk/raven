"""End-to-end test for the AIOS FastAPI gateway via TestClient."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from raven.cli.aios_cmd import create_aios_app
from raven.core.auth.tokens import token_manager


@pytest.fixture
def client():
    app = create_aios_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers():
    token = token_manager.create_token("e2e-admin", "admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers():
    token = token_manager.create_token("e2e-user", "user")
    return {"Authorization": f"Bearer {token}"}


class TestAiosGatewayE2E:
    def test_health_endpoint_public(self, client):
        resp = client.get("/aios/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch("aios.api.bridge._client")
    def test_ai_endpoint(self, mock_client, client, admin_headers):
        from ravencode.api.client import AIResponse

        mock_client.ask = AsyncMock(return_value=AIResponse(text="hello world", model="gpt4", provider="openai"))

        resp = client.post("/aios/ai", json={"prompt": "hi", "task": "code"}, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "hello world"
        assert data["provider"] == "openai"

    def test_exec_endpoint_requires_auth(self, client):
        resp = client.post("/aios/exec", json={"command": "echo test"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "Authentication required"

    def test_exec_endpoint_rejects_invalid_token(self, client):
        resp = client.post(
            "/aios/exec",
            json={"command": "echo test"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_exec_endpoint_forbidden_for_user_role(self, client, user_headers):
        resp = client.post("/aios/exec", json={"command": "echo test"}, headers=user_headers)
        assert resp.status_code == 403

    def test_exec_endpoint_allowed_for_admin(self, client, admin_headers):
        resp = client.post("/aios/exec", json={"command": "echo hello-from-e2e"}, headers=admin_headers)
        assert resp.status_code == 200
        assert "hello-from-e2e" in resp.json()["output"]

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows cmd.exe shell operators")
    def test_exec_endpoint_blocks_shell_operators(self, client, admin_headers):
        resp = client.post(
            "/aios/exec",
            json={"command": "git status && echo PWNED_BY_SHELL_OP"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "not allowed" in resp.json()["output"].lower()
        assert "PWNED_BY_SHELL_OP" not in resp.json()["output"]

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows cmd.exe shell operators")
    def test_exec_endpoint_blocks_pipe(self, client, admin_headers):
        resp = client.post(
            "/aios/exec",
            json={"command": "echo a | del C:\\Windows\\win.ini"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "not allowed" in resp.json()["output"].lower()
