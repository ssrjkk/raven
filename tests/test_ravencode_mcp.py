from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from ravencode.mcp import http_transport
from ravencode.mcp.server import MCPServer, run_mcp_server
from ravencode.runtime.tools import get_tool_definitions


def find_route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") == path and method in route.methods:
            return route.endpoint
    return None


def _req(**overrides: object) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = {}
    for key, val in overrides.items():
        setattr(req, key, val)
    return req


class TestMCPHttpTransport:
    @pytest.fixture
    def router(self):
        return http_transport.create_mcp_router()

    @pytest.fixture(autouse=True)
    def authorized(self):
        with patch("ravencode.mcp.http_transport.authorize_request", new=AsyncMock(return_value=True)) as mock_auth:
            yield mock_auth

    @pytest.fixture(autouse=True)
    def _no_subscriber_is_left_behind(self):
        """The event registry is one process-wide object shared with the gateway transport, so a client
        this file subscribed is a client every later file publishes to."""
        before = dict(http_transport._sse_transport._subscribers)
        yield
        subscribers = http_transport._sse_transport._subscribers
        subscribers.clear()
        subscribers.update(before)

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
            result = await endpoint(request=_req())
        assert result == [{"name": "shell", "description": "run", "parameters": {"type": "object"}}]

    async def test_tools_non_function_wrapper(self, router) -> None:
        defs = [{"name": "x", "description": "d", "parameters": {}}]
        with patch("ravencode.mcp.http_transport.get_tool_definitions", return_value=defs):
            endpoint = find_route(router, "/mcp/tools", "GET")
            result = await endpoint(request=_req())
        assert result[0]["name"] == "x"

    async def test_rpc_valid(self, router) -> None:
        req = _req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        with patch(
            "ravencode.mcp.http_transport._mcp_server.handle_request",
            new_callable=AsyncMock,
            return_value={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        ):
            endpoint = find_route(router, "/mcp/rpc", "POST")
            resp = await endpoint(request=req)
        assert json.loads(resp.body)["result"]["ok"] is True

    async def test_rpc_parse_error(self, router) -> None:
        req = _req(json=AsyncMock(side_effect=ValueError("bad json")))
        endpoint = find_route(router, "/mcp/rpc", "POST")
        resp = await endpoint(request=req)
        assert resp.status_code == 400
        assert json.loads(resp.body)["error"]["code"] == -32700

    async def test_rpc_invalid_request(self, router) -> None:
        req = _req(json=AsyncMock(return_value=["not", "a", "dict"]))
        endpoint = find_route(router, "/mcp/rpc", "POST")
        resp = await endpoint(request=req)
        assert resp.status_code == 400
        assert json.loads(resp.body)["error"]["code"] == -32600

    async def test_call_tool(self, router) -> None:
        req = _req(json=AsyncMock(return_value={"arguments": {"cmd": "echo hi"}}))
        with patch("ravencode.mcp.http_transport.execute_tool_public", new_callable=AsyncMock, return_value="hi"):
            endpoint = find_route(router, "/mcp/tools/{name}", "POST")
            resp = await endpoint("read", request=req)
        assert json.loads(resp.body) == {"result": "hi"}

    async def test_call_tool_default_body(self, router) -> None:
        req = _req(json=AsyncMock(return_value={}))
        with patch("ravencode.mcp.http_transport.execute_tool_public", new_callable=AsyncMock, return_value="ok"):
            endpoint = find_route(router, "/mcp/tools/{name}", "POST")
            resp = await endpoint("read", request=req)
        assert json.loads(resp.body) == {"result": "ok"}

    async def test_call_tool_refuses_a_name_the_operator_denied(self, router, monkeypatch: pytest.MonkeyPatch) -> None:
        """The REST half answers from the policy the RPC half already consulted.

        `/mcp/tools/{name}` handed `execute_tool_public` any name it was given, so a caller refused on
        `/mcp/rpc` could run the same tool by POSTing to this route instead.
        """
        monkeypatch.setattr("raven.core.config.settings.tools_deny", "shell")
        req = _req(json=AsyncMock(return_value={"arguments": {"cmd": "id"}}))
        with patch("ravencode.mcp.http_transport.execute_tool_public", new_callable=AsyncMock) as executor:
            endpoint = find_route(router, "/mcp/tools/{name}", "POST")
            resp = await endpoint("shell", request=req)
        assert resp.status_code == 403
        assert "TOOLS_DENY" in json.loads(resp.body)["error"]
        executor.assert_not_awaited()

    async def test_call_tool_requires_auth(self, router, authorized) -> None:
        authorized.return_value = False
        req = _req(json=AsyncMock(return_value={}))
        endpoint = find_route(router, "/mcp/tools/{name}", "POST")
        with pytest.raises(HTTPException) as exc:
            await endpoint("shell", request=req)
        assert exc.value.status_code == 401

    async def test_rpc_requires_auth(self, router, authorized) -> None:
        authorized.return_value = False
        req = _req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        endpoint = find_route(router, "/mcp/rpc", "POST")
        with pytest.raises(HTTPException) as exc:
            await endpoint(request=req)
        assert exc.value.status_code == 401

    async def test_tools_requires_auth(self, router, authorized) -> None:
        authorized.return_value = False
        endpoint = find_route(router, "/mcp/tools", "GET")
        with pytest.raises(HTTPException) as exc:
            await endpoint(request=_req())
        assert exc.value.status_code == 401

    async def test_events_requires_auth(self, router, authorized) -> None:
        authorized.return_value = False
        endpoint = find_route(router, "/mcp/events", "GET")
        with pytest.raises(HTTPException) as exc:
            await endpoint(request=_req())
        assert exc.value.status_code == 401

    async def test_events(self, router) -> None:
        endpoint = find_route(router, "/mcp/events", "GET")
        resp = await endpoint(request=_req())
        assert resp.media_type == "text/event-stream"

    async def test_the_stream_delivers_what_the_transport_published(self, router) -> None:
        """Not a patched `stream()`: the frame has to come out of the queue the route subscribed."""
        endpoint = find_route(router, "/mcp/events", "GET")
        resp = await endpoint(request=_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        for _ in range(200):
            if http_transport._sse_transport._subscribers:
                break
            await asyncio.sleep(0)
        await http_transport._sse_transport.send("tool_call", {"tool": "read", "status": "ok"})
        frame = await asyncio.wait_for(reading, timeout=2)
        assert frame == 'event: tool_call\ndata: {"tool": "read", "status": "ok"}\n\n'
        await frames.aclose()


class TestMCPServer:
    async def test_initialize(self) -> None:
        server = MCPServer()
        result = await server.handle_request({"method": "initialize", "id": 1, "params": {}})
        assert result is not None
        assert result["result"]["serverInfo"]["name"] == "ravencode"
        assert "tools" in result["result"]["capabilities"]

    async def test_tools_list(self) -> None:
        server = MCPServer()
        defs = [
            {
                "name": "a",
                "description": "d",
                "inputSchema": {"type": "object"},
                "annotations": {"destructiveHint": False, "openWorldHint": False},
            }
        ]
        with patch("raven.core.mcp.server.get_mcp_tool_definitions", return_value=defs):
            result = await server.handle_request({"method": "tools/list", "id": 2, "params": {}})
        assert result is not None
        assert result["result"]["tools"] == [
            {
                "name": "a",
                "description": "d",
                "inputSchema": {"type": "object"},
                "annotations": {"destructiveHint": False, "openWorldHint": False},
            }
        ]

    async def test_notification_yields_no_response(self) -> None:
        server = MCPServer()
        assert await server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    async def test_ping(self) -> None:
        server = MCPServer()
        result = await server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "ping"})
        assert result == {"jsonrpc": "2.0", "id": 9, "result": {}}

    async def test_tools_call_delegates_when_the_policy_allows_it(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.execute_tool_public", new_callable=AsyncMock, return_value="out") as executor:
            result = await server.handle_request(
                {"method": "tools/call", "id": 3, "params": {"name": "read", "arguments": {"path": "README.md"}}}
            )
        assert result is not None
        assert result["result"]["content"] == [{"type": "text", "text": "out"}]
        executor.assert_awaited_once()

    async def test_tools_call_refuses_a_denied_tool_without_reaching_the_executor(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.execute_tool_public", new_callable=AsyncMock, return_value="out") as executor:
            result = await server.handle_request(
                {"method": "tools/call", "id": 3, "params": {"name": "shell", "arguments": {"cmd": "x"}}}
            )
        assert result is not None
        text = result["result"]["content"][0]["text"]
        assert text.startswith("[denied]") and "TOOLS_DENY" in text, text
        assert result["result"]["isError"] is True
        executor.assert_not_awaited()

    async def test_unknown_method(self) -> None:
        server = MCPServer()
        result = await server.handle_request({"method": "nope", "id": 4, "params": {}})
        assert result is not None and "error" in result
        assert result["error"]["code"] == -32601
        assert "nope" in result["error"]["message"]

    async def test_run_answers_initialize(self, mcp_stdio) -> None:
        server = MCPServer()
        frames = await mcp_stdio(server, '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n')
        assert frames[0]["result"]["serverInfo"] == {"name": "ravencode", "version": server.server_version}

    async def test_run_survives_a_blank_frame(self, mcp_stdio) -> None:
        # Framing inherited from the shared loop: a blank line must not end the session.
        transcript = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        assert [f["id"] for f in await mcp_stdio(MCPServer(), transcript)] == [1, 2]

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
