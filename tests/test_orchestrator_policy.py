from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from raven.core.agents.orchestrator import AgentContext, AgentOrchestrator
from raven.core.agents.profiles import resolve_profile
from raven.core.config import settings
from raven.core.llm import LLMResponse, ToolCall
from raven.core.security.tool_policy import ToolPolicyEvaluator, mcp_deny_reason, policy_from_settings
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

LF = chr(10)
RAN: list[str] = []
_PARAMS = {"text": {"type": "string", "required": True}}
_DOTTED_NAME = re.compile(r"^[a-z_]+\.[a-z_]+$")


def _backticked(text: str) -> set[str]:
    return {token for token in set(re.findall(r"`([^`]+)`", text)) if _DOTTED_NAME.match(token)}


def _probe(name: str) -> Callable[..., Any]:
    def _handler(**kwargs: Any) -> str:
        RAN.append(name)
        return f"ran:{name}"

    return _handler


def _registry(*names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(
            ToolSpec(
                name=name,
                description=f"policy probe {name}",
                parameters=_PARAMS,
                handler=_probe(name),
                category="test",
            )
        )
    return registry


class _FakeLLM:
    """Serves scripted turns and records what the model was actually shown."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.seen: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: Any = None, model: str | None = None) -> LLMResponse:
        self.seen.append(messages)
        return self._responses.pop(0) if self._responses else LLMResponse(content="done")


def _orchestrator(registry: ToolRegistry, llm: _FakeLLM | None = None) -> AgentOrchestrator:
    return AgentOrchestrator(
        llm=llm or _FakeLLM(),  # type: ignore[arg-type]
        tool_registry=registry,
        planner_enabled=False,
        critic_enabled=False,
        reflect_enabled=False,
    )


def _ctx(workspace: Path | None = None) -> AgentContext:
    return AgentContext(query="probe", workspace=workspace)


@pytest.fixture
def switches(monkeypatch: pytest.MonkeyPatch) -> None:
    RAN.clear()
    monkeypatch.setattr(settings, "tools_allow", "")
    monkeypatch.setattr(settings, "exec_ask_mode", "off")
    monkeypatch.setattr(settings, "workspace_only", False)


async def _safe(orch: AgentOrchestrator, name: str) -> dict[str, Any]:
    call = ToolCall(id="1", name=name, arguments={"text": "hi"})
    return await orch._execute_tool_safe(call, resolve_profile("debugger"), _ctx())


async def test_a_tool_the_operator_denied_never_reaches_the_handler(
    switches: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", "probe_read")
    result = await _safe(_orchestrator(_registry("probe_read")), "probe_read")
    assert "TOOLS_DENY" in result["error"], result
    assert RAN == []


async def test_exec_class_tools_follow_exec_security(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", "")
    result = await _safe(_orchestrator(_registry("probe_shell")), "probe_shell")
    assert "operator policy" in result["error"], result
    assert RAN == []


async def test_exec_security_full_lets_the_same_tool_run(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "full")
    monkeypatch.setattr(settings, "tools_deny", "")
    result = await _safe(_orchestrator(_registry("probe_shell")), "probe_shell")
    assert result == {"result": "ran:probe_shell"}, result
    assert RAN == ["probe_shell"]


async def test_a_plain_tool_runs_under_the_shipped_defaults(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", "")
    result = await _safe(_orchestrator(_registry("probe_read")), "probe_read")
    assert result == {"result": "ran:probe_read"}, result


async def test_the_shipped_deny_list_reaches_this_registry(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.config import _DEFAULT_TOOLS_DENY

    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", ",".join(_DEFAULT_TOOLS_DENY))
    orch = _orchestrator(_registry("nodes_list"))
    assert "denied" in (await _safe(orch, "nodes_list"))["error"]
    assert RAN == []


async def test_the_orchestrator_builds_the_policy_the_agent_path_builds(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.config import _DEFAULT_TOOLS_DENY

    monkeypatch.setattr(settings, "tools_deny", ",".join(_DEFAULT_TOOLS_DENY))
    expected = policy_from_settings(profile="full")
    orch = _orchestrator(_registry("probe_read"))
    assert orch._tool_policy.profile == "full"
    assert orch._tool_policy._deny == expected._deny
    assert orch._tool_policy._allow == expected._allow
    assert "nodes_list" in orch._tool_policy._deny


async def test_the_mcp_surface_refuses_what_the_orchestrator_refuses(
    switches: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", "")
    result = await _safe(_orchestrator(_registry("probe_git_push")), "probe_git_push")
    assert "operator policy" in result["error"], result
    assert await mcp_deny_reason("probe_git_push", {}) != ""
    assert RAN == []


async def test_auto_memory_recall_stops_when_the_operator_denies_the_tool(
    switches: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exec_security", "full")
    monkeypatch.setattr(settings, "tools_deny", "")
    assert await _orchestrator(_registry("search_memory"))._recall_memory("anything") == "ran:search_memory"
    RAN.clear()
    monkeypatch.setattr(settings, "tools_deny", "search_memory")
    assert await _orchestrator(_registry("search_memory"))._recall_memory("anything") == ""
    assert RAN == []


async def test_the_refusal_is_what_the_model_is_shown(switches: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "tools_deny", "")
    llm = _FakeLLM(
        [
            LLMResponse(content="", tool_calls=[ToolCall(id="1", name="probe_shell", arguments={"text": "hi"})]),
            LLMResponse(content="I could not run that."),
        ]
    )
    orch = AgentOrchestrator(
        llm=llm,  # type: ignore[arg-type]
        tool_registry=_registry("probe_shell"),
        planner_enabled=False,
        critic_enabled=False,
        reflect_enabled=False,
        max_total_iterations=2,
    )
    result = await orch.execute("run something", profile_override="debugger")
    assert RAN == []
    assert result.content == "I could not run that."
    shown = str(llm.seen[-1])
    assert "operator policy" in shown, shown


def _plugin_tool_names() -> set[str]:
    import raven.plugins
    from raven.core.plugin_loader import PluginLoader

    loader = PluginLoader()
    for plugin_dir in sorted(Path(raven.plugins.__file__).parent.iterdir(), key=lambda d: d.name):
        if plugin_dir.is_dir() and plugin_dir.name != "__pycache__":
            loader.load_from_dir(plugin_dir)
    return {tool.name for tool in loader.tools}


def _registry_tool_names() -> set[str]:
    from raven.tools.register_all import create_tool_registry

    return {spec.name for spec in create_tool_registry().list()}


@pytest.fixture(scope="module")
def surfaces() -> set[str]:
    return _plugin_tool_names() | _registry_tool_names()


def test_every_default_deny_name_names_a_real_tool(surfaces: set[str]) -> None:
    from raven.core.config import _DEFAULT_TOOLS_DENY

    inert = sorted(set(_DEFAULT_TOOLS_DENY) - surfaces)
    assert inert == [], inert


def test_the_example_deny_line_names_only_real_tools(surfaces: set[str]) -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    line = next(entry for entry in text.splitlines() if entry.startswith("TOOLS_DENY="))
    value = line.split("=", 1)[1].strip()
    assert value == "", "an example value replaces the built-in default list, so it must name real tools"
    assert {name for name in surfaces if name.startswith("group:")} == set(), "group:* is a rule name, not a tool"


def _bullet(text: str, marker: str) -> str:
    """One `- **marker** …` list item, and not the list it lives in.

    The items of a markdown list arrive as a single block when the page is split on blank lines, so
    reading the block would let the tool names of a sibling bullet — the ruleset's deny list, say —
    be asserted as part of the profile's allow-list.
    """
    block = next(b for b in text.split(LF + LF) if marker in b)
    lines = block.split(LF)
    start = next(i for i, line in enumerate(lines) if marker in line)
    end = next((i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("- ")), len(lines))
    return LF.join(lines[start:end])


def test_the_documented_messaging_profile_lists_the_real_plugin_tools(surfaces: set[str]) -> None:
    bullet = _bullet(Path("docs/security/overview.md").read_text(encoding="utf-8"), "**tool profiles**")
    documented = {token for token in _backticked(bullet) if "." in token}
    declared = ToolPolicyEvaluator(profile="messaging")._profiles["messaging"]
    assert documented == declared, (documented, declared)
    assert documented <= surfaces, sorted(documented - surfaces)


def test_the_documented_surfaces_all_include_the_orchestrator() -> None:
    doc = Path("docs/configuration.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| `EXEC_SECURITY`"))
    assert "orchestrator" in row, row
    assert "MCP" in row, row
