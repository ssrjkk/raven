from __future__ import annotations

import json
import pathlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from ravencode.runtime import tools as tools_pkg
from ravencode.runtime.tools import get_mcp_tool_definitions, is_dangerous
from ravencode.runtime.tools.definitions import MODULE_TOOLS
from ravencode.runtime.tools.sandbox_policy import _WEB_BROWSING_TOOLS

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_list_advertises_both_hints_for_every_tool() -> None:
    tools = get_mcp_tool_definitions()
    assert len(tools) == len(MODULE_TOOLS)
    for tool in tools:
        annotations = tool["annotations"]
        assert set(annotations) == {"destructiveHint", "openWorldHint"}, tool["name"]
        assert isinstance(annotations["destructiveHint"], bool)
        assert isinstance(annotations["openWorldHint"], bool)


def test_the_advertised_risk_is_the_risk_the_policy_enforces() -> None:
    tools = get_mcp_tool_definitions()
    mismatched = [t["name"] for t in tools if t["annotations"]["destructiveHint"] is not is_dangerous(t["name"])]
    assert mismatched == []
    open_world = sorted(t["name"] for t in tools if t["annotations"]["openWorldHint"])
    assert open_world == sorted(name for name in MODULE_TOOLS if name in _WEB_BROWSING_TOOLS)
    destructive = [t["name"] for t in tools if t["annotations"]["destructiveHint"]]
    assert len(destructive) > 10, len(destructive)


def test_the_hint_follows_the_table_not_a_hardcoded_list(monkeypatch: pytest.MonkeyPatch) -> None:
    tools_pkg._build_tool_definitions.cache_clear()
    spec = dict(MODULE_TOOLS["read"])
    spec["dangerous"] = True
    monkeypatch.setitem(MODULE_TOOLS, "read", spec)
    try:
        listed = {tool["name"]: tool for tool in get_mcp_tool_definitions()}
        assert listed["read"]["annotations"]["destructiveHint"] is True
    finally:
        monkeypatch.undo()
        tools_pkg._build_tool_definitions.cache_clear()


async def test_the_stdio_frame_carries_the_annotations() -> None:
    from raven.core.mcp.server import MCPServer

    response = await MCPServer().handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert response is not None
    tools: list[dict[str, Any]] = response["result"]["tools"]
    assert len(tools) == len(MODULE_TOOLS)
    by_name = {tool["name"]: tool for tool in tools}
    assert by_name["bash"]["annotations"] == {"destructiveHint": True, "openWorldHint": False}
    assert by_name["read"]["annotations"]["destructiveHint"] is False


async def test_the_ravencode_server_serves_the_same_hints() -> None:
    from ravencode.mcp.server import MCPServer as RavencodeMCPServer

    response = await RavencodeMCPServer().handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    assert response is not None
    tools = response["result"]["tools"]
    assert sum(1 for tool in tools if tool["annotations"]["destructiveHint"]) > 10


def test_the_http_route_returns_the_plain_json_list_plus_hints() -> None:
    from raven.core.mcp.http_transport import create_mcp_router

    app = FastAPI()
    app.include_router(create_mcp_router())
    with patch("raven.core.mcp.auth.token_manager") as token_manager:
        token_manager.validate_token = AsyncMock(return_value={"user_id": "u1", "role": "admin"})
        with TestClient(app) as client:
            response = client.get("/mcp/tools", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    body = json.loads(response.text)
    assert len(body) == len(MODULE_TOOLS)
    for entry in body:
        assert {"name", "description", "parameters", "annotations"} <= set(entry)
    bash = next(entry for entry in body if entry["name"] == "bash")
    assert bash["annotations"] == {"destructiveHint": True, "openWorldHint": False}


def test_both_mcp_surfaces_read_the_annotated_builder() -> None:
    for relative in ("raven/core/mcp/server.py", "raven/core/mcp/http_transport.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "get_mcp_tool_definitions" in source, relative
        assert "get_tool_definitions" not in source, relative


def test_the_documented_counts_are_the_registry_counts() -> None:
    doc = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
    tools = get_mcp_tool_definitions()
    destructive = sum(1 for tool in tools if tool["annotations"]["destructiveHint"])
    open_world = sum(1 for tool in tools if tool["annotations"]["openWorldHint"])
    assert f"All {len(tools)} tools" in doc, len(tools)
    assert f"the {destructive} tools" in doc, destructive
    assert f"the {open_world} that leave the machine" in doc, open_world
    assert "`annotations`" in doc
