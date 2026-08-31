from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from raven.core.mcp.http_transport import create_mcp_router


def _auth_req(**overrides: object) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer test-token"}
    for key, val in overrides.items():
        setattr(req, key, val)
    return req


@pytest.fixture
def authed():
    with patch("raven.core.mcp.http_transport.token_manager") as tm:
        tm.validate_token.return_value = {"user_id": "u1", "role": "admin"}
        yield tm


class TestMCPHttp:
    @pytest.fixture
    def router(self):
        return create_mcp_router()

    def test_router_routes(self, router) -> None:
        routes = {r.path for r in router.routes}
        assert "/mcp/rpc" in routes
        assert "/mcp/tools" in routes
        assert "/mcp/tools/{name}" in routes
        assert "/mcp/events" in routes
        assert "/mcp/health" in routes

    async def test_health_endpoint(self, router, authed) -> None:
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/health" and "GET" in route.methods:
                resp = await route.endpoint()
                assert resp["status"] == "ok"
                return

    async def test_tools_endpoint(self, router, authed) -> None:
        defs = [{"function": {"name": "read_file", "description": "Read a file", "parameters": {}}}]
        with patch("raven.core.mcp.http_transport.get_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    resp = await route.endpoint(request=_auth_req())
                    body = json.loads(resp.body)
                    assert len(body) == 1
                    assert body[0]["name"] == "read_file"
                    return

    async def test_tools_endpoint_no_function_wrapper(self, router, authed) -> None:
        defs = [{"name": "write_file", "description": "Write a file", "parameters": {}}]
        with patch("raven.core.mcp.http_transport.get_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    resp = await route.endpoint(request=_auth_req())
                    body = json.loads(resp.body)
                    assert len(body) == 1
                    assert body[0]["name"] == "write_file"
                    return

    async def test_rpc_valid(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert body["result"]["serverInfo"]["name"] == "raven-mcp"
                return

    async def test_rpc_unauthorized(self, router) -> None:
        req = _auth_req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                assert resp.status_code == 401
                return

    async def test_rpc_parse_error(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(side_effect=ValueError("bad json")))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32700
                return

    async def test_rpc_invalid_type(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value="not a dict"))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32600
                return

    async def test_call_tool(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={"arguments": {"x": 1}}))
        with patch("raven.core.mcp.http_transport.execute_tool", new=AsyncMock(return_value="done")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="echo", request=req)
                    body = json.loads(resp.body)
                    assert body["result"] == "done"
                    return

    async def test_call_tool_default_args(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={}))
        with patch("raven.core.mcp.http_transport.execute_tool", new=AsyncMock(return_value="ok")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="ping", request=req)
                    assert json.loads(resp.body)["result"] == "ok"
                    return

    async def test_tools_requires_auth(self, router) -> None:
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                resp = await route.endpoint(request=_auth_req())
                assert resp.status_code == 401
                return

    async def test_call_tool_requires_auth(self, router) -> None:
        req = _auth_req(json=AsyncMock(return_value={}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                resp = await route.endpoint(name="ping", request=req)
                assert resp.status_code == 401
                return
