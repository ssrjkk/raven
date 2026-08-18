from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from ravencode.mcp import http_transport
from ravencode.mcp.server import MCPServer, run_mcp_server
from ravencode.runtime.tools import get_tool_definitions


def find_route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") == path and method in route.methods:
            return route.endpoint
    return None


class TestMCPHttpTransport:
    @pytest.fixture
    def router(self):
        return http_transport.create_mcp_router()

    def test_router_routes(self, router) -> None:
        routes = {r.path for r in router.routes}
        assert {"/mcp/rpc", "/mcp/tools", "/mcp/tools/{name}", "/mcp/events", "/mcp/health"} <= routes

    async def test_health(self, router) -> None:
        endpoint = find_route(router, "/mcp/health", "GET")
        assert await endpoint() == {"status": "ok", "server": "ravencode-mcp"}

    async def test_tools(self, router) -> None:
        defs = [{"function": {"name": "shell", "description": "run", "parameters": {"type": "object"}}}]
        with patch("ravencode.mcp.http_transport.get_tool_definitions", return_value=defs):
            endpoint = find_route(router, "/mcp/tools", "GET")
            result = await endpoint()
        assert result == [{"name": "shell", "description": "run", "parameters": {"type": "object"}}]

    async def test_tools_non_function_wrapper(self, router) -> None:
        defs = [{"name": "x", "description": "d", "parameters": {}}]
        with patch("ravencode.mcp.http_transport.get_tool_definitions", return_value=defs):
            endpoint = find_route(router, "/mcp/tools", "GET")
            result = await endpoint()
        assert result[0]["name"] == "x"

    async def test_rpc_valid(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}})
        with patch(
            "ravencode.mcp.http_transport._mcp_server.handle_request",
            new_callable=AsyncMock,
            return_value={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        ):
            endpoint = find_route(router, "/mcp/rpc", "POST")
            resp = await endpoint(request=req)
        assert json.loads(resp.body)["result"]["ok"] is True

    async def test_rpc_parse_error(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(side_effect=ValueError("bad json"))
        endpoint = find_route(router, "/mcp/rpc", "POST")
        resp = await endpoint(request=req)
        assert resp.status_code == 400
        assert json.loads(resp.body)["error"]["code"] == -32700

    async def test_rpc_invalid_request(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value=["not", "a", "dict"])
        endpoint = find_route(router, "/mcp/rpc", "POST")
        resp = await endpoint(request=req)
        assert resp.status_code == 400
        assert json.loads(resp.body)["error"]["code"] == -32600

    async def test_call_tool(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={"arguments": {"cmd": "echo hi"}})
        with patch("ravencode.mcp.http_transport.execute_tool", new_callable=AsyncMock, return_value="hi"):
            endpoint = find_route(router, "/mcp/tools/{name}", "POST")
            resp = await endpoint("shell", request=req)
        assert json.loads(resp.body) == {"result": "hi"}

    async def test_call_tool_default_body(self, router) -> None:
        req = MagicMock(spec=Request)
        req.json = AsyncMock(return_value={})
        with patch("ravencode.mcp.http_transport.execute_tool", new_callable=AsyncMock, return_value="ok"):
            endpoint = find_route(router, "/mcp/tools/{name}", "POST")
            resp = await endpoint("shell", request=req)
        assert json.loads(resp.body) == {"result": "ok"}

    async def test_events(self, router) -> None:
        endpoint = find_route(router, "/mcp/events", "GET")
        req = MagicMock(spec=Request)
        resp = await endpoint(request=req)
        assert resp.media_type == "text/event-stream"

    async def test_events_stream_yields_and_unsubscribes(self, router) -> None:
        endpoint = find_route(router, "/mcp/events", "GET")
        req = MagicMock(spec=Request)

        async def fake_stream(client_id: str):
            yield "data: one\n\n"
            yield "data: two\n\n"

        with (
            patch("ravencode.mcp.http_transport._sse_transport.stream", new=fake_stream),
            patch("ravencode.mcp.http_transport._sse_transport.subscribe") as sub,
            patch("ravencode.mcp.http_transport._sse_transport.unsubscribe") as unsub,
        ):
            resp = await endpoint(request=req)
            chunks = [c async for c in resp.body_iterator]
        assert chunks == ["data: one\n\n", "data: two\n\n"]
        sub.assert_called_once()
        unsub.assert_called_once()


class TestMCPServer:
    async def test_initialize(self) -> None:
        server = MCPServer()
        result = await server.handle_request({"method": "initialize", "id": 1, "params": {}})
        assert result["result"]["serverInfo"]["name"] == "ravencode"
        assert "tools" in result["result"]["capabilities"]

    async def test_tools_list(self) -> None:
        server = MCPServer()
        defs = [{"function": {"name": "a"}}]
        with patch("ravencode.mcp.server.get_tool_definitions", return_value=defs):
            result = await server.handle_request({"method": "tools/list", "id": 2, "params": {}})
        assert result["result"]["tools"] == defs

    async def test_tools_call(self) -> None:
        server = MCPServer()
        with patch("ravencode.mcp.server.execute_tool", new_callable=AsyncMock, return_value="out"):
            result = await server.handle_request(
                {"method": "tools/call", "id": 3, "params": {"name": "shell", "arguments": {"cmd": "x"}}}
            )
        assert result["result"]["content"] == [{"type": "text", "text": "out"}]

    async def test_unknown_method(self) -> None:
        server = MCPServer()
        result = await server.handle_request({"method": "nope", "id": 4, "params": {}})
        assert result["error"]["code"] == -32601
        assert "nope" in result["error"]["message"]

    async def test_read_request_valid(self, monkeypatch) -> None:
        server = MCPServer()
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO('{"method": "initialize"}\n'))
        req = await server._read_request()
        assert req == {"method": "initialize"}

    async def test_read_request_empty_and_invalid(self, monkeypatch) -> None:
        import io

        server = MCPServer()
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert await server._read_request() is None
        monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))
        assert await server._read_request() is None
        monkeypatch.setattr("sys.stdin", io.StringIO("not json\n"))
        assert await server._read_request() is None

    async def test_run_loop(self, monkeypatch) -> None:
        import io

        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        responses: list[dict[str, object] | None] = [{"method": "initialize"}, None]
        calls = {"n": 0}

        async def fake_read() -> dict[str, object] | None:
            val = responses[calls["n"]]
            calls["n"] += 1
            return val

        server = MCPServer()
        server._read_request = fake_read  # type: ignore[method-assign]
        await server.run()
        assert '"serverInfo"' in out.getvalue()

    async def test_stop_sets_running_false(self) -> None:
        server = MCPServer()
        server._running = True
        server.stop()
        assert server._running is False

    async def test_run_mcp_server(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.mcp.server.run_mcp_server", lambda: None)
        from ravencode.mcp.server import run_mcp_server as rms

        assert rms() is None

    async def test_run_mcp_server_creates_and_runs(self, monkeypatch) -> None:
        fake_server = MagicMock()
        fake_server.run = AsyncMock()
        monkeypatch.setattr("ravencode.mcp.server.MCPServer", lambda: fake_server)
        await run_mcp_server()
        fake_server.run.assert_awaited_once()
