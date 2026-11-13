"""A write has to be allowed by a table, not merely be free of a rule that forbids it.

`auth_middleware` used to reject only *anonymous* writes, so any account created through the open
`/api/auth/register` could run CI/CD, rewrite LLM provider credentials, drive the debugger, enroll
voice biometrics and execute MCP tools. These tests pin the replacement: an unlisted write needs
the operator, and the list of writes that do not is short and checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from raven.core.auth.models import Permission
from raven.core.auth.rbac import rbac
from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.middleware import (
    MUTATING_METHODS,
    USER_MUTATING_PERMISSIONS,
    auth_middleware,
    write_permission,
)
from raven.gateway.daemon import RavenFlowDaemon

_OPERATOR_KEY = "operator-key-under-test"

_WRITE_PATHS = (
    "/api/echo",
    "/api/sessions",
    "/api/media/upload",
    "/api/task/run",
    "/api/agent",
    "/api/agents",
    "/api/connections/providers",
    "/api/cicd/run",
    "/api/voice/enroll",
    "/api/media/generate",
    "/aios/completion",
    "/mcp/rpc",
    "/api/auth/login",
    "/api/webhooks/generic",
)


def _ok() -> dict[str, bool]:
    return {"ok": True}


def _gateway_client() -> TestClient:
    app = FastAPI()
    app.middleware("http")(auth_middleware)
    for path in _WRITE_PATHS:
        app.add_api_route(path, _ok, methods=["POST"])
    app.add_api_route("/api/echo", _ok, methods=["GET"])
    return TestClient(app)


@pytest.fixture(autouse=True)
def _operator_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_secret_key", SecretStr(_OPERATOR_KEY))


async def _bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await token_manager.create_token(f'u:{role}', role)}"}


class TestWritePermissionTable:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/echo",
            "/api/agents",
            "/api/cicd/run",
            "/api/connections/providers/openai",
            "/api/voice/enroll",
            "/api/tests/run",
            "/api/memory/restore",
            "/api/debug/start",
            "/mcp/rpc",
            "/mcp/tools/shell",
            "/aios/ai",
            "/aios/sessions/abc123",
        ],
    )
    def test_unlisted_write_needs_the_operator(self, path: str) -> None:
        assert write_permission(path) is Permission.ADMIN_WRITE

    @pytest.mark.parametrize(
        ("path", "permission"),
        [
            ("/api/sessions", Permission.CHAT),
            ("/api/sessions/abc123", Permission.CHAT),
            ("/api/collab/sessions/abc123/join", Permission.CHAT),
            ("/api/media/upload", Permission.CHAT),
            ("/api/v1/commands/theme/generate", Permission.CHAT),
            ("/api/agent", Permission.TASK_RUN),
            ("/api/task/run", Permission.TASK_RUN),
            ("/api/task/abc123/cancel", Permission.TASK_RUN),
            ("/api/routine/create", Permission.ROUTINE_WRITE),
            ("/api/routine/pause/abc123", Permission.ROUTINE_WRITE),
            ("/api/monitor/trigger/abc123", Permission.MONITOR_WRITE),
            ("/aios/completion", Permission.CODE_READ),
            ("/aios/workspace/write", Permission.CODE_WRITE),
            ("/api/rag/search", Permission.CODE_READ),
            ("/api/rag/index", Permission.CODE_WRITE),
            ("/api/knowledge/search", Permission.CODE_READ),
            ("/api/knowledge/entity", Permission.CODE_WRITE),
        ],
    )
    def test_listed_write_needs_the_permission_it_is_listed_under(self, path: str, permission: Permission) -> None:
        assert write_permission(path) is permission

    def test_the_read_table_loosens_nothing_the_write_table_claims(self) -> None:
        # PATH_PERMISSIONS also gates reads on these prefixes; it wins, so `/api/media/` cannot
        # quietly hand out the generate endpoint the read table reserves for the operator.
        assert write_permission("/api/media/generate") is Permission.ADMIN_WRITE
        assert write_permission("/aios/agent") is Permission.ADMIN_WRITE

    def test_a_table_entry_grants_a_permission_a_plain_account_actually_holds(self) -> None:
        # An entry naming an operator-only permission would be a no-op dressed up as an allowance.
        for prefix, permission in USER_MUTATING_PERMISSIONS.items():
            assert rbac.has_permission("user", permission), f"{prefix} grants {permission.value}, which no user has"


class TestGatewayWriteGate:
    async def test_anonymous_write_is_still_asked_for_a_credential(self) -> None:
        client = _gateway_client()
        assert client.post("/api/echo").status_code == 401

    async def test_plain_account_denied_with_the_permission_it_lacks(self) -> None:
        client = _gateway_client()
        resp = client.post("/api/cicd/run", headers=await _bearer("user"))
        assert resp.status_code == 403
        assert resp.json()["required"] == Permission.ADMIN_WRITE.value

    @pytest.mark.parametrize("method", sorted(MUTATING_METHODS))
    async def test_every_mutating_method_is_gated(self, method: str) -> None:
        client = _gateway_client()
        resp = client.request(method, "/api/echo", headers=await _bearer("user"))
        assert resp.status_code == 403

    async def test_a_sibling_path_does_not_inherit_a_listed_permission(self) -> None:
        # `/api/agent` is listed for a chat account; `/api/agents` is registry introspection.
        client = _gateway_client()
        assert client.post("/api/agent", headers=await _bearer("user")).status_code == 200
        assert client.post("/api/agents", headers=await _bearer("user")).status_code == 403

    async def test_listed_writes_reach_the_route(self) -> None:
        client = _gateway_client()
        headers = await _bearer("user")
        assert client.post("/api/sessions", headers=headers).status_code == 200
        assert client.post("/api/media/upload", headers=headers).status_code == 200

    async def test_an_operator_key_reaches_every_write(self) -> None:
        client = _gateway_client()
        assert client.post("/api/echo", headers={"X-Raven-Key": _OPERATOR_KEY}).status_code == 200

    async def test_a_read_only_account_may_still_chat(self) -> None:
        client = _gateway_client()
        headers = await _bearer("viewer")
        assert client.post("/api/sessions", headers=headers).status_code == 200
        assert client.post("/api/task/run", headers=headers).status_code == 403
        assert client.post("/api/agent", headers=headers).status_code == 403

    async def test_a_banned_account_may_not_write_anywhere(self) -> None:
        client = _gateway_client()
        headers = await _bearer("banned")
        assert client.post("/api/sessions", headers=headers).status_code == 403

    async def test_the_write_rule_leaves_an_authorized_read_alone(self) -> None:
        client = _gateway_client()
        assert client.get("/api/echo", headers=await _bearer("user")).status_code == 200

    async def test_the_public_write_prefixes_stay_public(self) -> None:
        client = _gateway_client()
        assert client.post("/api/auth/login").status_code == 200
        assert client.post("/api/webhooks/generic").status_code == 200


class TestDaemonWriteGate:
    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        return TestClient(RavenFlowDaemon(port=0, data_dir=tmp_path).app)

    def test_anonymous_agent_run_is_refused(self, client: TestClient) -> None:
        assert client.post("/api/agent", json={"message": "hi"}).status_code == 401

    def test_health_stays_open(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    @pytest.mark.parametrize(
        "path", ["/api/sandbox", "/api/routing", "/api/tools/run_shell", "/api/connections/providers"]
    )
    async def test_a_plain_account_cannot_drive_the_daemon(self, client: TestClient, path: str) -> None:
        resp = client.post(path, headers=await _bearer("user"))
        assert resp.status_code == 403
        assert resp.json()["required"] == Permission.ADMIN_WRITE.value

    async def test_a_read_only_account_cannot_run_an_agent(self, client: TestClient) -> None:
        assert client.post("/api/agent", json={"message": "hi"}, headers=await _bearer("viewer")).status_code == 403

    def test_the_operator_key_still_drives_it(self, client: TestClient) -> None:
        resp = client.post("/api/routing?pattern=*&agent_id=coder", headers={"X-Raven-Key": _OPERATOR_KEY})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_a_socket_without_a_credential_is_closed(self, client: TestClient) -> None:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass

    async def test_a_socket_only_refuses_what_the_role_may_not_run(self, client: TestClient) -> None:
        token = await token_manager.create_token("u:viewer", "viewer")
        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_text('{"type": "message", "content": "hi"}')
            assert "task:run" in ws.receive_json()["content"]
            ws.send_text('{"type": "ping"}')
            assert ws.receive_json()["type"] == "pong"
