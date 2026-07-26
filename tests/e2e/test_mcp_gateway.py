from __future__ import annotations

import asyncio
import json

import pytest

from raven.core.models import IncomingMessage, PluginTool
from raven.tools.mcp_tools import create_mcp_plugin_tools, register_mcp_tools
from raven.tools.register_all import create_tool_registry


class _FakeMCPClient:
    def __init__(self, name: str, tools: list[dict[str, object]]) -> None:
        self._name = name
        self._tools = tools

    @property
    def tools(self) -> list[dict[str, object]]:
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, object] | None = None) -> list[dict[str, str]]:
        if tool_name == "echo":
            return [{"type": "text", "text": json.dumps(arguments)}]
        if tool_name == "fail":
            raise RuntimeError("simulated failure")
        return [{"type": "text", "text": f"called {tool_name}"}]


class _FakeMCPPool:
    def __init__(self, clients: dict[str, _FakeMCPClient] | None = None):
        self._clients = clients or {}

    def get_client(self, name: str) -> _FakeMCPClient | None:
        return self._clients.get(name)

    def connect(self, name: str, command: list[str], **kwargs):
        raise NotImplementedError

    async def disconnect_all(self):
        self._clients.clear()

    @property
    def connected_count(self) -> int:
        return len(self._clients)


@pytest.mark.e2e
class TestMCPGatewayIntegration:
    def test_mcp_tools_registered_in_registry(self):
        pool = _FakeMCPPool({
            "math": _FakeMCPClient("math", [
                {"name": "add", "description": "Add two numbers", "inputSchema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                }},
                {"name": "subtract", "description": "Subtract two numbers", "inputSchema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                }},
            ]),
        })
        registry = create_tool_registry(pool)
        tools = registry.list(category="mcp")
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "mcp_math_add" in names
        assert "mcp_math_subtract" in names

    def test_mcp_plugin_tools_created(self):
        pool = _FakeMCPPool({
            "fs": _FakeMCPClient("fs", [
                {"name": "read", "description": "Read a file", "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                }},
            ]),
        })
        tools = create_mcp_plugin_tools(pool)  # type: ignore[arg-type]
        assert len(tools) == 1
        assert tools[0].name == "mcp_fs_read"
        assert isinstance(tools[0], PluginTool)

    async def test_mcp_pool_disconnect_all(self):
        pool = _FakeMCPPool({
            "server_a": _FakeMCPClient("server_a", [{"name": "tool1"}]),
            "server_b": _FakeMCPClient("server_b", [{"name": "tool2"}]),
        })
        assert pool.connected_count == 2
        await pool.disconnect_all()
        assert pool.connected_count == 0

    async def test_mcp_tool_call_via_handler(self):
        pool = _FakeMCPPool({
            "math": _FakeMCPClient("math", [
                {"name": "echo", "description": "Echo args", "inputSchema": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                }},
            ]),
        })
        registry = create_tool_registry(pool)
        spec = registry.get("mcp_math_echo")
        assert spec is not None
        result = await spec.handler(msg="hello")
        data = json.loads(result)
        assert data == {"msg": "hello"}

    async def test_mcp_tool_call_error_returns_error_string(self):
        pool = _FakeMCPPool({
            "bad": _FakeMCPClient("bad", [
                {"name": "fail", "description": "Always fails"},
            ]),
        })
        registry = create_tool_registry(pool)
        spec = registry.get("mcp_bad_fail")
        assert spec is not None
        result = await spec.handler()
        assert result.startswith("[error]")

    async def test_mcp_unknown_server_returns_error(self):
        pool = _FakeMCPPool({})
        registry = create_tool_registry(pool)
        assert registry.list(category="mcp") == []

    @pytest.mark.xfail(reason="Pre-existing: gateway handle_message user lookup not wired in test fixture")
    async def test_mcp_in_gateway_mcp_command(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/mcp",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert any("no mcp" in m.content.lower() for m in channel.sent_messages)

    async def test_mcp_empty_config_does_not_fail(self, gateway):
        assert gateway.mcp is not None
        assert gateway.mcp.connected_count == 0

    async def test_mcp_tool_registry_with_empty_pool(self):
        pool = _FakeMCPPool({})
        registry = create_tool_registry(pool)
        assert registry.count >= 10
        mcp_tools = registry.list(category="mcp")
        assert len(mcp_tools) == 0

    async def test_mcp_concurrent_calls(self):
        pool = _FakeMCPPool({
            "srv": _FakeMCPClient("srv", [
                {"name": "echo", "description": "Echo", "inputSchema": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                }},
            ]),
        })
        registry = create_tool_registry(pool)
        spec = registry.get("mcp_srv_echo")
        assert spec is not None
        results = await asyncio.gather(*[spec.handler(x=i) for i in range(10)])
        assert len(results) == 10
        for i, r in enumerate(results):
            data = json.loads(r)
            assert data == {"x": i}
