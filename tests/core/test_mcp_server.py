from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.mcp.server import MCPServer


class TestMCPServer:
    async def test_handle_initialize(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({"method": "initialize", "id": 1, "params": {}})
        assert resp is not None and resp["result"]["protocolVersion"] == "2025-03-26"
        assert resp["result"]["serverInfo"]["name"] == "raven-mcp"

    async def test_handle_tools_list(self) -> None:
        server = MCPServer()
        with patch(
            "raven.core.mcp.server.get_tool_definitions",
            return_value=[{"function": {"name": "test", "description": "d", "parameters": {"type": "object"}}}],
        ):
            resp = await server.handle_request({"method": "tools/list", "id": 2, "params": {}})
            assert resp is not None and resp["result"]["tools"] == [
                {"name": "test", "description": "d", "inputSchema": {"type": "object"}}
            ]

    async def test_handle_notification_returns_none(self) -> None:
        server = MCPServer()
        assert await server.handle_request({"method": "notifications/initialized", "params": {}}) is None

    async def test_handle_ping(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({"method": "ping", "id": 7, "params": {}})
        assert resp == {"jsonrpc": "2.0", "id": 7, "result": {}}

    async def test_handle_logging_set_level(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({"method": "logging/setLevel", "id": 8, "params": {"level": "info"}})
        assert resp is not None
        assert resp["result"] == {}
        assert resp["id"] == 8

    async def test_handle_tools_call(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.execute_tool_public", new=AsyncMock(return_value="executed")):
            resp = await server.handle_request({
                "method": "tools/call", "id": 3,
                "params": {"name": "echo", "arguments": {"msg": "hello"}},
            })
            assert resp is not None
            assert resp["result"]["content"][0]["text"] == "executed"

    async def test_handle_tools_call_missing_name(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({
            "method": "tools/call", "id": 4, "params": {"arguments": {}},
        })
        assert resp is not None and "error" in resp
        assert resp["error"]["code"] == -32602

    async def test_handle_unknown_method(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({"method": "unknown", "id": 5, "params": {}})
        assert resp is not None and "error" in resp
        assert resp["error"]["code"] == -32601
        assert "unknown" in resp["error"]["message"].lower()

    async def test_handle_missing_method(self) -> None:
        server = MCPServer()
        resp = await server.handle_request({"id": 6, "params": {}})
        assert resp is not None and "error" in resp
        assert resp["error"]["code"] == -32601

    async def test_read_request_valid(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.sys.stdin.readline", return_value='{"method":"ping","id":1}\n'):
            req = await server._read_request()
            assert req is not None
            assert req["method"] == "ping"

    async def test_read_request_empty(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.sys.stdin.readline", return_value=""):
            req = await server._read_request()
            assert req is None

    async def test_read_request_blank(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.sys.stdin.readline", return_value="  \n"):
            req = await server._read_request()
            assert req is None

    async def test_read_request_invalid_json(self) -> None:
        server = MCPServer()
        with patch("raven.core.mcp.server.sys.stdin.readline", return_value="not json\n"):
            req = await server._read_request()
            assert req is None

    def test_stop(self) -> None:
        server = MCPServer()
        server._running = True
        server.stop()
        assert server._running is False
