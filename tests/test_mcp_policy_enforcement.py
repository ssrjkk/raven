from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from ravencode.runtime.tools.definitions import MODULE_TOOLS

CALLS: list[str] = []


def _probe(name: str, dangerous: bool = False) -> dict[str, Any]:
    async def _handler(**kwargs: Any) -> str:
        CALLS.append(name)
        return "handler ran"

    return {
        "name": name,
        "description": f"policy probe {name}",
        "handler": _handler,
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        "dangerous": dangerous,
    }


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> None:
    CALLS.clear()
    monkeypatch.setitem(MODULE_TOOLS, "policy_probe", _probe("policy_probe"))
    monkeypatch.setitem(MODULE_TOOLS, "shell_probe", _probe("shell_probe", dangerous=True))
    monkeypatch.setattr("raven.core.config.settings.tools_profile", "messaging")
    monkeypatch.setattr("raven.core.config.settings.tools_deny", "")
    monkeypatch.setattr("raven.core.config.settings.tools_allow", "")
    monkeypatch.setattr("raven.core.config.settings.exec_security", "full")
    monkeypatch.setattr("raven.core.config.settings.exec_ask_mode", "off")
    monkeypatch.setattr("raven.core.config.settings.workspace_only", False)


async def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from raven.core.mcp.server import MCPServer

    response = await MCPServer().handle_request(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}
    )
    assert response is not None
    return response


async def test_the_operator_deny_list_is_honoured_over_mcp(probes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.config.settings.tools_deny", "policy_probe")
    response = await _call("policy_probe")
    text = response["result"]["content"][0]["text"]
    assert text.startswith("[denied]") and "TOOLS_DENY" in text, text
    assert response["result"]["isError"] is True
    assert CALLS == []


async def test_a_tool_nobody_denied_still_runs(probes: None) -> None:
    response = await _call("policy_probe")
    assert response["result"]["content"][0]["text"] == "handler ran"
    assert CALLS == ["policy_probe"]


async def test_exec_class_tools_follow_exec_security(probes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.config.settings.exec_security", "deny")
    response = await _call("shell_probe")
    text = response["result"]["content"][0]["text"]
    assert "[denied]" in text and "security=deny" in text, text
    assert CALLS == []

    monkeypatch.setattr("raven.core.config.settings.exec_security", "full")
    response = await _call("shell_probe")
    assert response["result"]["content"][0]["text"] == "handler ran"
    assert CALLS == ["shell_probe"]


async def test_the_mcp_layer_does_not_confine_paths_the_tool_layer_allows(
    probes: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two roots exist: WORKSPACE_PATH belongs to the gateway, --workspace to these tools.

    Confining MCP arguments against the gateway's root would refuse paths that
    `ravencode/runtime/workspace.py:confine` accepts, so the MCP policy layer stays out of
    paths and the tool layer remains the single confinement point.
    """
    from ravencode.runtime import workspace as rav_workspace

    ravencode_root = tmp_path / "ravencode-ws"
    ravencode_root.mkdir()
    gateway_root = tmp_path / "gateway-ws"
    gateway_root.mkdir()
    monkeypatch.setattr("raven.core.config.settings.workspace_only", True)
    monkeypatch.setattr("raven.core.config.settings.workspace_path", str(gateway_root))
    monkeypatch.setattr(rav_workspace, "workspace_root", lambda: ravencode_root)

    inside = ravencode_root / "notes.md"
    inside.write_text("hello", encoding="utf-8")
    assert str(rav_workspace.confine(str(inside))) == str(inside)

    response = await _call("policy_probe", {"path": str(inside)})
    assert response["result"]["content"][0]["text"] == "handler ran", response
    assert CALLS == ["policy_probe"]

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(PermissionError, match="outside workspace"):
        rav_workspace.confine(str(outside / "secret.txt"))


async def test_an_allow_list_narrows_the_surface(probes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.config.settings.tools_allow", "policy_probe")
    response = await _call("shell_probe")
    assert "[denied]" in response["result"]["content"][0]["text"]
    assert CALLS == []


def test_the_http_route_refuses_before_the_handler_runs(probes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.mcp.http_transport import create_mcp_router

    monkeypatch.setattr("raven.core.config.settings.tools_deny", "policy_probe")
    app = FastAPI()
    app.include_router(create_mcp_router())
    with patch("raven.core.mcp.auth.token_manager") as token_manager:
        token_manager.validate_token = AsyncMock(return_value={"user_id": "u1", "role": "viewer"})
        with TestClient(app) as client:
            response = client.post(
                "/mcp/tools/policy_probe",
                json={"arguments": {}},
                headers={"Authorization": "Bearer test-token"},
            )
    assert response.status_code == 403
    assert "TOOLS_DENY" in response.text
    assert CALLS == []


def test_the_rpc_endpoint_refuses_too(probes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.mcp.http_transport import create_mcp_router

    monkeypatch.setattr("raven.core.config.settings.tools_deny", "policy_probe")
    app = FastAPI()
    app.include_router(create_mcp_router())
    with patch("raven.core.mcp.auth.token_manager") as token_manager:
        token_manager.validate_token = AsyncMock(return_value={"user_id": "u1", "role": "viewer"})
        with TestClient(app) as client:
            response = client.post(
                "/mcp/rpc",
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "policy_probe"}},
                headers={"Authorization": "Bearer test-token"},
            )
    payload = json.loads(response.text)
    assert payload["result"]["isError"] is True
    assert payload["result"]["content"][0]["text"].startswith("[denied]")
    assert CALLS == []


def test_the_agent_path_and_the_mcp_path_share_one_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.agent import agent as agent_module
    from raven.core.security.tool_policy import policy_from_settings

    monkeypatch.setattr("raven.core.config.settings.tools_deny", "a_tool,b_tool")
    monkeypatch.setattr("raven.core.config.settings.tools_allow", "")
    monkeypatch.setattr("raven.core.config.settings.exec_security", "ask")
    monkeypatch.setattr("raven.core.config.settings.exec_ask_mode", "always")

    shared = policy_from_settings().to_dict()
    assert sorted(shared["deny"]) == ["a_tool", "b_tool"]
    assert shared["exec_security"] == "ask" and shared["exec_ask"] == "always"

    mcp_side = policy_from_settings(profile="full", workspace_only=False).to_dict()
    assert mcp_side["profile"] == "full"
    assert mcp_side["workspace_only"] is False
    assert mcp_side["deny"] == shared["deny"], "the MCP surface must read the same deny list"

    recipe = inspect.getsource(agent_module.Agent._init_tool_policy)
    assert "policy_from_settings()" in recipe, "the agent path keeps its own copy of the recipe"


def test_the_documented_exec_class_count_matches_the_registry() -> None:
    from raven.core.security.tool_policy import is_exec_class

    exec_tools = sorted(name for name in MODULE_TOOLS if is_exec_class(name))
    doc = (Path(__file__).resolve().parents[1] / "docs" / "mcp.md").read_text(encoding="utf-8")
    assert f"the {len(exec_tools)} exec-class tools" in doc, (len(exec_tools), exec_tools)

def test_the_default_deny_list_touches_the_served_surface_once() -> None:
    from raven.core.config import _DEFAULT_TOOLS_DENY

    touched = sorted(set(MODULE_TOOLS) & set(_DEFAULT_TOOLS_DENY))
    assert len(touched) == 1, touched
    doc = (Path(__file__).resolve().parents[1] / "docs" / "mcp.md").read_text(encoding="utf-8")
    assert f"the default `TOOLS_DENY` touches exactly one, `{touched[0]}`" in doc, touched
