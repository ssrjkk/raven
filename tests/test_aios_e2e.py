"""End-to-end test for the AIOS FastAPI gateway via TestClient."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

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
def admin_headers(client):
    token = asyncio.run(token_manager.create_token("e2e-admin", "admin"))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client):
    token = asyncio.run(token_manager.create_token("e2e-user", "user"))
    return {"Authorization": f"Bearer {token}"}


class TestAiosSecurityHeaders:
    """`create_aios_app()` binds a port a browser can reach, and nothing anywhere asked it for the
    headers the gateway app does send -- not one test referenced `security_headers_middleware`."""

    def test_every_response_carries_the_security_headers(self, client):
        resp = client.get("/aios/health")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]

    def test_headers_reach_a_response_the_route_never_returned(self, client):
        """The 401 is produced by the auth layer, outside the route -- the middleware is registered
        outermost so a refusal is still not frameable or MIME-sniffable."""
        resp = client.post("/aios/exec", json={"command": "echo test"})
        assert resp.status_code == 401
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"


class TestAdminBootstrap:
    """The loop a fresh install cannot complete on its own, run over the gateway's real RBAC middleware.

    `/api/auth/register` writes `role='user'` and `/api/auth/users` -- the route that hands out roles --
    is admin-only, so before `raven security promote` exists in the process nobody can sign in as admin
    and the command's whole job is to close that.
    """

    PASSWORD = "Sup3rSecret!"

    def _register(self, client: TestClient, name: str) -> str:
        resp = client.post("/api/auth/register", json={"username": name, "password": self.PASSWORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "user", "registration is not a path to admin"
        token: str = resp.json()["token"]
        return token

    def test_a_registered_account_cannot_reach_the_route_that_hands_out_roles(self, client: TestClient) -> None:
        token = self._register(client, f"bootstrap-{uuid4().hex[:8]}")
        refused = client.get("/api/auth/users", headers={"Authorization": f"Bearer {token}"})
        assert refused.status_code == 403
        assert refused.json()["required"] == "admin:users"

    def test_promote_makes_the_same_account_an_admin_the_gateway_admits(self, client: TestClient) -> None:
        from click.testing import CliRunner

        from raven.cli.security_cmd import security_group

        name = f"bootstrap-{uuid4().hex[:8]}"
        old_token = self._register(client, name)

        def who_am_i(token: str) -> dict[str, str]:
            body: dict[str, str] = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
            return body

        assert who_am_i(old_token)["user_id"] == f"user:{name}", "the session is live before the promotion"

        result = CliRunner().invoke(security_group, ["promote", name])
        assert result.exit_code == 0, result.output
        assert "role user -> admin" in " ".join(result.output.split())

        # auth_sessions stores the role as it was at login, so a session minted before the promotion is
        # worth nothing to an admin account; the caller has to fall back to anonymous, not to "user".
        assert who_am_i(old_token)["user_id"] == "anonymous", "the pre-promotion session was revoked"

        login = client.post("/api/auth/login", json={"username": name, "password": self.PASSWORD})
        assert login.status_code == 200, login.text
        assert login.json()["role"] == "admin"
        admitted = client.get("/api/auth/users", headers={"Authorization": f"Bearer {login.json()['token']}"})
        assert admitted.status_code == 200
        assert name in [row["username"] for row in admitted.json()]

    def test_the_bootstrap_password_is_the_one_the_registration_route_would_accept(self, client: TestClient) -> None:
        """`promote` enforces the documented policy, so the CLI cannot mint a privileged account the
        HTTP path would have refused."""
        from click.testing import CliRunner

        from raven.cli.security_cmd import security_group

        name = f"bootstrap-{uuid4().hex[:8]}"
        weak = CliRunner().invoke(security_group, ["promote", name, "--password", "short1!"])
        assert weak.exit_code == 1
        assert "8 characters" in weak.output

        refused = client.post("/api/auth/register", json={"username": name, "password": "short1!"})
        assert refused.status_code == 422, "both paths refuse the same credential"


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
