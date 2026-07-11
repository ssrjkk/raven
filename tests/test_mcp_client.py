from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.mcp.channel_bridge import ChannelBridge
from raven.core.mcp.mcp_client import MCPClient, MCPClientPool
from raven.core.task_engine.tool_registry import ToolRegistry


class TestMCPClientResponses:
    @pytest.fixture
    def mock_process(self) -> MagicMock:
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.returncode = None
        return proc

    @staticmethod
    def _make_mock_proc() -> MagicMock:
        stdin_mock = MagicMock()
        stdin_mock.drain = AsyncMock(return_value=None)
        stdin_mock.write = MagicMock()
        proc = MagicMock()
        proc.stdin = stdin_mock
        proc.stdout = MagicMock()
        proc.returncode = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = MagicMock()
        return proc

    async def test_connect_initialize(self) -> None:
        with patch("raven.core.mcp.mcp_client.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            proc = self._make_mock_proc()

            init_resp = json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"serverInfo": {"name": "test-mcp", "version": "1.0"}},
            }) + "\n"

            tools_resp = json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "result": {"tools": [{"name": "greet", "description": "Say hello"}]},
            }) + "\n"

            responses = iter([init_resp.encode(), tools_resp.encode()])

            async def readline():
                return next(responses)

            proc.stdout.readline = readline
            mock_spawn.return_value = proc

            client = MCPClient(["test-server"])
            await client.connect()
            assert client._server_info == {"name": "test-mcp", "version": "1.0"}
            assert len(client.tools) == 1
            await client.disconnect()

    async def test_call_tool(self) -> None:
        with patch("raven.core.mcp.mcp_client.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            proc = self._make_mock_proc()

            responses = [
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "m"}}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "hi"}]}}),
            ]

            async def readline():
                return (responses.pop(0) + "\n").encode() if responses else b""

            proc.stdout.readline = readline
            mock_spawn.return_value = proc

            client = MCPClient(["tool-server"])
            await client.connect()
            content = await client.call_tool("greet", {"name": "world"})
            assert content == [{"type": "text", "text": "hi"}]
            await client.disconnect()

    async def test_error_response(self) -> None:
        with patch("raven.core.mcp.mcp_client.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            proc = self._make_mock_proc()

            responses = [
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "m"}}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "error": {"code": -32602, "message": "Bad params"}}),
            ]

            async def readline():
                return (responses.pop(0) + "\n").encode() if responses else b""

            proc.stdout.readline = readline
            mock_spawn.return_value = proc

            client = MCPClient(["err-server"])
            await client.connect()
            with pytest.raises(Exception, match="Bad params"):
                await client.call_tool("bad")
            await client.disconnect()

    async def test_to_llm_tools(self) -> None:
        client = MCPClient(["dummy"])
        client._tools = [{"name": "greet", "description": "Say hello", "inputSchema": {"type": "object"}}]
        llm_tools = client.to_llm_tools()
        assert len(llm_tools) == 1
        assert llm_tools[0]["function"]["name"] == "mcp_greet"

    async def test_disconnect_not_connected(self) -> None:
        client = MCPClient(["dummy"])
        await client.disconnect()

    async def test_call_before_connect(self) -> None:
        client = MCPClient(["dummy"])
        with pytest.raises(Exception, match="Not connected"):
            await client.call_tool("x")


class TestMCPClientPool:
    @staticmethod
    def _make_mock_proc() -> MagicMock:
        stdin_mock = MagicMock()
        stdin_mock.drain = AsyncMock(return_value=None)
        stdin_mock.write = MagicMock()
        proc = MagicMock()
        proc.stdin = stdin_mock
        proc.stdout = MagicMock()
        proc.returncode = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = MagicMock()
        return proc

    async def test_pool_connect(self) -> None:
        pool = MCPClientPool()
        with patch("raven.core.mcp.mcp_client.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            proc = self._make_mock_proc()

            responses = [
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "m"}}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}),
            ]

            async def readline():
                return (responses.pop(0) + "\n").encode() if responses else b""

            proc.stdout.readline = readline
            mock_spawn.return_value = proc

            client = await pool.connect("my-server", ["test-server"])
            assert pool.connected_count == 1
            assert pool.get_client("my-server") is client
            await pool.disconnect_all()

    async def test_pool_disconnect_all(self) -> None:
        pool = MCPClientPool()
        pool._clients["x"] = MagicMock()
        pool._clients["y"] = MagicMock()
        await pool.disconnect_all()
        assert pool.connected_count == 0

    async def test_all_tools_prefixed(self) -> None:
        pool = MCPClientPool()
        c1 = MagicMock()
        c1.tools = [{"name": "tool_a"}]
        c2 = MagicMock()
        c2.tools = [{"name": "tool_b"}]
        pool._clients["svc1"] = c1
        pool._clients["svc2"] = c2
        tools = pool.all_tools()
        names = {t["name"] for t in tools}
        assert "mcp_svc1_tool_a" in names
        assert "mcp_svc2_tool_b" in names

    async def test_get_missing(self) -> None:
        pool = MCPClientPool()
        assert pool.get_client("nonexistent") is None


class TestChannelBridge:
    @pytest.fixture
    def bridge(self) -> ChannelBridge:
        return ChannelBridge()

    async def test_send_message_ok(self) -> None:
        send_fn = AsyncMock()
        bridge = ChannelBridge(send_fn=send_fn)
        result = await bridge._send_message("telegram", "hello")
        assert "Message sent" in result
        send_fn.assert_awaited_once_with("telegram", "default", "hello")

    async def test_send_message_no_send_fn(self) -> None:
        bridge = ChannelBridge()
        result = await bridge._send_message("telegram", "hello")
        assert "no send function" in result

    async def test_send_message_error(self) -> None:
        async def failing(ch: str, sid: str, text: str) -> None:
            raise RuntimeError("channel down")

        bridge = ChannelBridge(send_fn=failing)
        result = await bridge._send_message("slack", "hi")
        assert "error" in result.lower()
        assert "channel down" in result

    async def test_send_message_truncated(self) -> None:
        send_fn = AsyncMock()
        bridge = ChannelBridge(send_fn=send_fn)
        long_msg = "x" * 5000
        result = await bridge._send_message("discord", long_msg)
        assert "Message sent" in result
        args = send_fn.call_args[0]
        sent_text = args[2]
        assert len(sent_text) < 4500  # truncated
        assert "truncated" in sent_text  # truncation notice in message body

    async def test_list_channels(self) -> None:
        bridge = ChannelBridge()
        result = await bridge._list_channels()
        assert "telegram" in result
        assert "slack" in result

    async def test_register_tools(self) -> None:
        bridge = ChannelBridge()
        registry = ToolRegistry()
        bridge.register_tools(registry)
        assert registry.get("send_message") is not None
        assert registry.get("list_channels") is not None

    async def test_set_send_fn(self) -> None:
        bridge = ChannelBridge()
        send_fn = AsyncMock()
        bridge.set_send_fn(send_fn)
        result = await bridge._send_message("test", "msg")
        assert "Message sent" in result
        send_fn.assert_awaited_once()

    async def test_register_tools_duplicate_safe(self) -> None:
        bridge = ChannelBridge()
        registry = ToolRegistry()
        bridge.register_tools(registry)
        bridge.register_tools(registry)
        assert registry.count == 2
