from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.mcp_bridge import MCPBridge


class _FakeClient:
    def __init__(self, tools: list[dict[str, Any]] | None = None) -> None:
        self.tools = tools or []
        self._call_result: Any = None
        self._call_exc: Exception | None = None

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._call_exc is not None:
            raise self._call_exc
        return self._call_result


class _FakePool:
    def __init__(self) -> None:
        self._clients: dict[str, _FakeClient] = {}
        self.connect = AsyncMock()
        self.disconnect_all = AsyncMock()

    def get_client(self, name: str) -> _FakeClient | None:
        return self._clients.get(name)

    @property
    def connected_count(self) -> int:
        return len(self._clients)


def _bridge(monkeypatch: pytest.MonkeyPatch) -> tuple[MCPBridge, _FakePool]:
    pool = _FakePool()
    monkeypatch.setattr("raven.core.gateway.mcp_bridge.MCPClientPool", lambda: pool)
    monkeypatch.setattr("raven.core.gateway.mcp_bridge.ChannelBridge", lambda send_fn=None: MagicMock())
    return MCPBridge(), pool


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.mcp_bridge.settings", MagicMock(mcp_servers=""))


def test_init_builds_pool_and_channel_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    assert isinstance(bridge.pool, _FakePool)
    assert bridge.pool is pool
    assert isinstance(bridge.channel_bridge, MagicMock)


async def test_start_no_servers_returns_early(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    await bridge.start()
    pool.connect.assert_not_awaited()


async def test_start_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.mcp_bridge.settings", MagicMock(mcp_servers="{not json"))
    bridge, pool = _bridge(monkeypatch)
    await bridge.start()
    pool.connect.assert_not_awaited()


async def test_start_skips_missing_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.mcp_bridge.settings", MagicMock(mcp_servers='{"srv": {"cwd": "/x"}}')
    )
    bridge, pool = _bridge(monkeypatch)
    await bridge.start()
    pool.connect.assert_not_awaited()


async def test_start_connects_without_plugin_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.mcp_bridge.settings",
        MagicMock(mcp_servers='{"srv": {"command": ["node", "s.js"], "cwd": "/x"}}'),
    )
    bridge, pool = _bridge(monkeypatch)
    pool.connect.return_value = _FakeClient(tools=[{"name": "a"}])
    await bridge.start()
    pool.connect.assert_awaited_once_with("srv", ["node", "s.js"], cwd="/x")


async def test_start_registers_plugin_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.mcp_bridge.settings",
        MagicMock(mcp_servers='{"srv": {"command": ["node", "s.js"]}}'),
    )
    bridge, pool = _bridge(monkeypatch)
    client = _FakeClient(
        tools=[{"name": "do", "description": "does", "inputSchema": {"properties": {"x": {"type": "string"}}}}]
    )
    pool.connect.return_value = client
    loader = MagicMock()
    loader.tools = []
    await bridge.start(plugin_loader=loader)
    assert len(loader.tools) == 1
    registered = loader.tools[0]
    assert registered.name == "mcp_srv_do"
    assert registered.description == "does"
    assert registered.parameters == {"x": {"type": "string"}}
    assert callable(registered.handler)


async def test_start_connect_error_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.mcp_bridge.settings",
        MagicMock(mcp_servers='{"srv": {"command": ["node", "s.js"]}}'),
    )
    bridge, pool = _bridge(monkeypatch)
    pool.connect.side_effect = RuntimeError("boom")
    await bridge.start()  # must not raise
    assert bridge.connected_count == 0


async def test_stop_disconnects_all(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    await bridge.stop()
    pool.disconnect_all.assert_awaited_once()


async def test_handler_missing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, _pool = _bridge(monkeypatch)
    handler = bridge._make_handler("ghost", "tool")
    assert await handler() == "[error] MCP server 'ghost' not connected"


async def test_handler_returns_text_from_list(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    client = _FakeClient()
    client._call_result = [{"text": "the answer"}]
    pool._clients["srv"] = client
    handler = bridge._make_handler("srv", "tool")
    assert await handler(a=1) == "the answer"


async def test_handler_list_dict_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    client = _FakeClient()
    result = [{"other": 1}]
    client._call_result = result
    pool._clients["srv"] = client
    handler = bridge._make_handler("srv", "tool")
    assert await handler() == str(result)


async def test_handler_plain_result(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    client = _FakeClient()
    client._call_result = "plain-value"
    pool._clients["srv"] = client
    handler = bridge._make_handler("srv", "tool")
    assert await handler() == "plain-value"


async def test_handler_call_error(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    client = _FakeClient()
    client._call_exc = RuntimeError("tool exploded")
    pool._clients["srv"] = client
    handler = bridge._make_handler("srv", "tool")
    assert await handler() == "[error] MCP tool call failed: tool exploded"


def test_connected_count_property(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    pool._clients["a"] = _FakeClient()
    pool._clients["b"] = _FakeClient()
    assert bridge.connected_count == 2


def test_list_servers_info(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, pool = _bridge(monkeypatch)
    pool._clients["srv"] = _FakeClient(tools=[{"name": "x"}, {"name": "y"}])
    pool._clients["gone"] = None  # type: ignore[assignment]
    infos = bridge.list_servers_info()
    assert {"name": "srv", "tools": 2} in infos
    assert {"name": "gone", "tools": 0} in infos
