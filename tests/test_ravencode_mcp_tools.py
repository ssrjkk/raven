"""Tests for MCP tool integration (ravencode.runtime.mcp_tools)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ravencode.runtime.mcp_tools import (
    _format_content,
    connect_mcp_servers,
    disconnect_mcp_servers,
    ensure_mcp_tools,
    register_client_tools,
)
from ravencode.runtime.tools import MODULE_TOOLS, _build_tool_definitions, get_tool_definitions


class FakeMCPClient:
    def __init__(self, tools: list[dict[str, Any]]):
        self._tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments or {}))
        return [{"type": "text", "text": f"echo:{name}:{(arguments or {}).get('x', '')}"}]


class FakePool:
    def __init__(self, client: FakeMCPClient | None = None, *, fail: bool = False) -> None:
        self._client = client
        self._fail = fail
        self.clients: dict[str, FakeMCPClient] = {}
        self.connect_cmds: list[tuple[str, list[str], Any]] = []
        self.disconnects = 0

    def get_client(self, name: str) -> FakeMCPClient | None:
        return self.clients.get(name)

    async def connect(self, name: str, cmd: list[str], cwd: Any = None) -> FakeMCPClient:
        self.connect_cmds.append((name, cmd, cwd))
        if self._fail:
            raise RuntimeError("spawn failed")
        assert self._client is not None
        self.clients[name] = self._client
        return self._client

    async def disconnect_all(self) -> None:
        self.disconnects += 1
        self.clients.clear()


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    # remove every mcp_ tool that leaked into the shared registry
    for name in [n for n in list(MODULE_TOOLS) if n.startswith("mcp_")]:
        MODULE_TOOLS.pop(name, None)
    _build_tool_definitions.cache_clear()
    from raven.core.mcp.mcp_client import get_mcp_pool
    from ravencode.runtime import mcp_tools

    get_mcp_pool()._clients.clear()
    mcp_tools._registered_servers.clear()
    mcp_tools._config_attempted = False


def test_register_adds_prefixed_tools() -> None:
    client = FakeMCPClient(
        [
            {"name": "search", "description": "Search stuff", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
        ]
    )
    registered = register_client_tools("github", client)
    assert registered == ["mcp_github_search"]
    assert "mcp_github_search" in MODULE_TOOLS
    tool = MODULE_TOOLS["mcp_github_search"]
    assert tool["dangerous"] is True
    assert "[MCP:github]" in tool["description"]
    assert tool["parameters"]["required"] == ["q"]
    # tool must be visible through the public definitions API
    names = {d["function"]["name"] for d in get_tool_definitions()}
    assert "mcp_github_search" in names


def test_register_sanitizes_unsafe_names() -> None:
    client = FakeMCPClient([{"name": "weird name/with.dots!"}])
    registered = register_client_tools("my server", client)
    assert registered == ["mcp_my_server_weird_name_with_dots_"]


def test_register_skips_duplicates() -> None:
    client = FakeMCPClient([{"name": "dup"}])
    first = register_client_tools("srv", client)
    second = register_client_tools("srv", client)
    assert first == ["mcp_srv_dup"]
    assert second == []


def test_register_skips_nameless_tools() -> None:
    client = FakeMCPClient([{"name": "   "}, {"name": "ok"}])
    assert register_client_tools("srv", client) == ["mcp_srv_ok"]


async def test_registered_handler_calls_client_and_formats() -> None:
    client = FakeMCPClient([{"name": "greet"}])
    register_client_tools("srv", client)
    handler = MODULE_TOOLS["mcp_srv_greet"]["handler"]
    result = await handler(x="hi")
    assert result == "echo:greet:hi"
    assert client.calls == [("greet", {"x": "hi"})]


async def test_connect_mcp_servers_skips_bad_specs() -> None:
    total = await connect_mcp_servers(
        [
            {"name": "", "command": "noop"},  # no name
            {"name": "nocmd"},  # no command
            {"name": "off", "command": "noop", "disabled": True},  # disabled
            "not-a-dict",  # garbage
        ]
    )
    assert total == 0


def test_format_content_variants() -> None:
    assert _format_content([{"type": "text", "text": "a"}, {"type": "image", "url": "x"}]) == "a\n[image content]"
    assert _format_content([]) == "(empty result)"
    assert _format_content(["plain"]) == "plain"
    assert _format_content("raw") == "raw"


async def test_connect_mcp_servers_happy_path() -> None:
    client = FakeMCPClient([{"name": "tool1"}, {"name": "tool2"}])
    pool = FakePool(client)
    with patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool):
        total = await connect_mcp_servers([{"name": "srv", "command": "bin", "args": ["a", "b"], "cwd": "."}])
    assert total == 2
    assert pool.connect_cmds == [("srv", ["bin", "a", "b"], ".")]
    assert {"mcp_srv_tool1", "mcp_srv_tool2"} <= set(MODULE_TOOLS)


async def test_connect_mcp_servers_failure_is_skipped() -> None:
    pool = FakePool(fail=True)
    with patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool):
        total = await connect_mcp_servers([{"name": "broken", "command": "bin"}])
    assert total == 0
    assert not [n for n in MODULE_TOOLS if n.startswith("mcp_broken")]


async def test_connect_mcp_servers_idempotent() -> None:
    client = FakeMCPClient([{"name": "t"}])
    pool = FakePool(client)
    with patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool):
        spec = [{"name": "srv", "command": "bin"}]
        assert await connect_mcp_servers(spec) == 1
        assert await connect_mcp_servers(spec) == 0
    assert len(pool.connect_cmds) == 1


async def test_ensure_mcp_tools_with_explicit_servers() -> None:
    client = FakeMCPClient([{"name": "t"}])
    pool = FakePool(client)
    with patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool):
        assert await ensure_mcp_tools([{"name": "srv", "command": "bin"}]) == 1


async def test_ensure_mcp_tools_reads_config_once() -> None:
    client = FakeMCPClient([{"name": "t"}])
    pool = FakePool(client)
    loader = MagicMock()
    loader.load_all.return_value = MagicMock(mcp_servers=[{"name": "srv", "command": "bin"}])
    with (
        patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool),
        patch("ravencode.config.loader.ConfigLoader", return_value=loader),
    ):
        assert await ensure_mcp_tools() == 1
        assert await ensure_mcp_tools() == 0
    assert loader.load_all.call_count == 1


async def test_ensure_mcp_tools_config_error_returns_zero() -> None:
    with patch("ravencode.config.loader.ConfigLoader", side_effect=RuntimeError("no config")):
        assert await ensure_mcp_tools() == 0


async def test_disconnect_mcp_servers_resets_state() -> None:
    client = FakeMCPClient([{"name": "t"}])
    pool = FakePool(client)
    with patch("ravencode.runtime.mcp_tools.get_mcp_pool", return_value=pool):
        await connect_mcp_servers([{"name": "srv", "command": "bin"}])
        from ravencode.runtime import mcp_tools

        assert mcp_tools._registered_servers == {"srv"}
        await disconnect_mcp_servers()
    assert pool.disconnects == 1
    assert not mcp_tools._registered_servers
    assert mcp_tools._config_attempted is False
