from __future__ import annotations

from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import mcp_tools as mcp_mod


class _FakeClient:
    def __init__(self, tools: list[dict[str, Any]], result: Any = None, raises: bool = False) -> None:
        self.tools = tools
        self._result = result
        self._raises = raises

    async def call_tool(self, _name: str, _params: dict[str, Any]) -> Any:
        if self._raises:
            raise RuntimeError("mcp transport down")
        return self._result


class _FakePool:
    def __init__(self, clients: dict[str, _FakeClient]) -> None:
        self._clients = clients

    def get_client(self, name: str) -> _FakeClient | None:
        return self._clients.get(name)


class TestMakeMcpHandler:
    @pytest.mark.asyncio
    async def test_pool_none_returns_error(self) -> None:
        handler = mcp_mod._make_mcp_handler("srv", "tool", None)
        assert await handler() == "[error] MCP server 'srv' not connected"

    @pytest.mark.asyncio
    async def test_client_missing_returns_error(self) -> None:
        pool: Any = _FakePool({})
        handler = mcp_mod._make_mcp_handler("srv", "tool", pool)
        assert await handler() == "[error] MCP server 'srv' not connected"

    @pytest.mark.asyncio
    async def test_result_list_with_text(self) -> None:
        client = _FakeClient([], result=[{"text": "hello"}])
        pool: Any = _FakePool({"srv": client})
        handler = mcp_mod._make_mcp_handler("srv", "tool", pool)
        assert await handler(a=1) == "hello"

    @pytest.mark.asyncio
    async def test_result_non_list_stringified(self) -> None:
        client = _FakeClient([], result="plain")
        pool: Any = _FakePool({"srv": client})
        assert await mcp_mod._make_mcp_handler("srv", "tool", pool)() == "plain"

    @pytest.mark.asyncio
    async def test_result_empty_list_stringified(self) -> None:
        client = _FakeClient([], result=[])
        pool: Any = _FakePool({"srv": client})
        assert await mcp_mod._make_mcp_handler("srv", "tool", pool)() == "[]"

    @pytest.mark.asyncio
    async def test_result_list_without_text_key(self) -> None:
        client = _FakeClient([], result=[{"data": 1}])
        pool: Any = _FakePool({"srv": client})
        assert await mcp_mod._make_mcp_handler("srv", "tool", pool)() == str([{"data": 1}])

    @pytest.mark.asyncio
    async def test_call_tool_exception(self) -> None:
        client = _FakeClient([], raises=True)
        pool: Any = _FakePool({"srv": client})
        out = await mcp_mod._make_mcp_handler("srv", "tool", pool)()
        assert out == "[error] MCP tool call failed: mcp transport down"


class TestRegisterMcpTools:
    def test_none_pool_noop(self) -> None:
        registry = ToolRegistry()
        mcp_mod.register_mcp_tools(registry, None)
        assert registry.list() == []

    def test_registers_with_schema_variants(self) -> None:
        tools: list[dict[str, Any]] = [
            {"name": "read", "description": "d1", "inputSchema": {"properties": {"p": {"type": "string"}}}},
            {"name": "write", "description": "d2", "parameters": {"properties": {"q": {"type": "integer"}}}},
            {"description": "no-name-no-schema"},
        ]
        pool: Any = _FakePool({"fs": _FakeClient(tools)})
        registry = ToolRegistry()
        mcp_mod.register_mcp_tools(registry, pool)
        assert registry.get("mcp_fs_read") is not None
        assert registry.get("mcp_fs_write") is not None
        assert registry.get("mcp_fs_unknown") is not None


class TestCreateMcpPluginTools:
    def test_none_pool_empty(self) -> None:
        assert mcp_mod.create_mcp_plugin_tools(None) == []

    def test_builds_plugin_tools(self) -> None:
        tools = [{"name": "ping", "description": "p", "inputSchema": {"properties": {"x": {}}}}]
        pool: Any = _FakePool({"net": _FakeClient(tools)})
        built = mcp_mod.create_mcp_plugin_tools(pool)
        assert len(built) == 1
        assert built[0].name == "mcp_net_ping"
