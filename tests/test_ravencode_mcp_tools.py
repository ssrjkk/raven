"""Tests for MCP tool integration (ravencode.runtime.mcp_tools)."""
from __future__ import annotations

from typing import Any

import pytest

from ravencode.runtime.mcp_tools import (
    _format_content,
    connect_mcp_servers,
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
