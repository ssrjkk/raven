from __future__ import annotations

import json
from typing import Any

import pytest


class TestMCPServer:
    def setup_method(self) -> None:
        from raven.core.mcp.server import MCPServer

        self.server = MCPServer()

    @pytest.mark.asyncio
    async def test_handle_initialize(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        result = await self.server.handle_request(req)
        assert result["result"]["protocolVersion"] == "2025-03-26"
        assert result["result"]["serverInfo"]["name"] == "raven-mcp"

    @pytest.mark.asyncio
    async def test_handle_tools_list(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        result = await self.server.handle_request(req)
        assert "result" in result
        assert "tools" in result["result"]

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 3, "method": "unknown/method", "params": {}}
        result = await self.server.handle_request(req)
        assert "error" in result
        assert result["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_missing_id(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "method": "unknown"}
        result = await self.server.handle_request(req)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mcp_router_health(self) -> None:
        from raven.core.mcp.http_transport import _mcp_server

        result = await _mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert result["result"]["serverInfo"]["name"] == "raven-mcp"

    def test_list_tools_route(self) -> None:
        defs = _get_tool_defs()
        assert isinstance(defs, list)

    @pytest.mark.asyncio
    async def test_call_tool_missing_name(self) -> None:
        from raven.core.mcp.server import MCPServer

        server = MCPServer()
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"arguments": {}}}
        result = await server.handle_request(req)
        assert "error" in result


def _get_tool_defs() -> list[dict[str, Any]]:
    from ravencode.runtime.tools import get_tool_definitions

    return get_tool_definitions()
