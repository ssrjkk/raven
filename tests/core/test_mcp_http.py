# mypy: ignore-errors
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from raven.core.mcp.http_transport import create_mcp_router


class TestMCPHttp:
    @pytest.fixture
    def router(self) -> None:
        return create_mcp_router()

    def test_router_routes(self, router) -> None:
        routes = {r.path for r in router.routes}
        assert "/mcp/rpc" in routes
        assert "/mcp/tools" in routes
        assert "/mcp/tools/{name}" in routes
        assert "/mcp/events" in routes
        assert "/mcp/health" in routes

    async def test_health_endpoint(self, router) -> None:
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/health" and "GET" in route.methods:
                resp = await route.endpoint()
                assert resp["status"] == "ok"
                return

    async def test_tools_endpoint(self, router) -> None:
        defs = [{"function": {"name": "read_file", "description": "Read a file", "parameters": {}}}]
        with patch("raven.core.mcp.http_transport.get_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    result = await route.endpoint()
                    assert isinstance(result, list)
                    assert len(result) == 1
                    assert result[0]["name"] == "read_file"
                    return

    async def test_tools_endpoint_no_function_wrapper(self, router) -> None:
        defs = [{"name": "write_file", "description": "Write a file", "parameters": {}}]
        with patch("raven.core.mcp.http_transport.get_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    result = await route.endpoint()
                    assert len(result) == 1
                    assert result[0]["name"] == "write_file"
                    return

    async def test_rpc_valid(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}})
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert body["result"]["serverInfo"]["name"] == "raven-mcp"
                return

    async def test_rpc_parse_error(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(side_effect=ValueError("bad json"))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32700
                return

    async def test_rpc_invalid_type(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value="not a dict")
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32600
                return

    async def test_call_tool(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={"arguments": {"x": 1}})
        with patch("raven.core.mcp.http_transport.execute_tool", new=AsyncMock(return_value="done")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="echo", request=req)
                    body = json.loads(resp.body)
                    assert body["result"] == "done"
                    return

    async def test_call_tool_default_args(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={})
        with patch("raven.core.mcp.http_transport.execute_tool", new=AsyncMock(return_value="ok")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="ping", request=req)
                    assert json.loads(resp.body)["result"] == "ok"
                    return
