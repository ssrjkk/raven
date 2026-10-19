from __future__ import annotations

from unittest.mock import AsyncMock, patch

from raven.core.mcp.server import MCPServer

_PING_1 = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
_PING_2 = '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'


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
            resp = await server.handle_request(
                {
                    "method": "tools/call",
                    "id": 3,
                    "params": {"name": "echo", "arguments": {"msg": "hello"}},
                }
            )
            assert resp is not None
            assert resp["result"]["content"][0]["text"] == "executed"

    async def test_handle_tools_call_missing_name(self) -> None:
        server = MCPServer()
        resp = await server.handle_request(
            {
                "method": "tools/call",
                "id": 4,
                "params": {"arguments": {}},
            }
        )
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

    def test_stop(self) -> None:
        server = MCPServer()
        server._running = True
        server.stop()
        assert server._running is False


class TestStdioFraming:
    """The loop owns the framing, so these drive run() over a canned transcript."""

    async def test_answers_every_frame(self, mcp_stdio) -> None:
        assert [r["id"] for r in await mcp_stdio(MCPServer(), _PING_1 + _PING_2)] == [1, 2]

    async def test_blank_line_does_not_end_the_session(self, mcp_stdio) -> None:
        # A blank line is framing, not a shutdown signal: the reader that treated it as EOF left the
        # host with a dead transport the moment it wrote one.
        transcript = _PING_1 + "\n" + _PING_2
        assert [r["id"] for r in await mcp_stdio(MCPServer(), transcript)] == [1, 2]

    async def test_malformed_frame_answers_and_keeps_serving(self, mcp_stdio) -> None:
        responses = await mcp_stdio(MCPServer(), _PING_1 + "oops\n" + _PING_2)
        assert responses[1] == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        assert responses[2]["id"] == 2

    async def test_non_object_frame_is_an_invalid_request(self, mcp_stdio) -> None:
        responses = await mcp_stdio(MCPServer(), "[1,2]\n" + _PING_1)
        assert responses[0]["error"]["code"] == -32600
        assert responses[1]["id"] == 1

    async def test_notification_gets_no_response(self, mcp_stdio) -> None:
        transcript = '{"jsonrpc":"2.0","method":"notifications/initialized"}\n' + _PING_1
        assert [r["id"] for r in await mcp_stdio(MCPServer(), transcript)] == [1]

    async def test_closed_stdin_ends_the_session(self, mcp_stdio) -> None:
        assert await mcp_stdio(MCPServer(), "") == []
