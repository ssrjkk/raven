"""The exec-class gate must cover a capability under every name it can be called by.

Measured before the fix: `is_exec_class` matched an underscore-token list against the raw tool
name, and plugin tools arrive namespaced (`raven/core/plugin_loader.py:288` builds
`<plugin_dir>.<tool>`). `process_kill` was exec-class and `process.kill` was not; `http_post` was
and `api.http_put`/`api.http_delete` were not; `code.run_python` was and
`memory.run_python` — the same handler imported into another plugin — was not. One token, `node_`,
matched nothing in the 243-name space at all, so `nodes_exec` was never in the class the docstring
says the task registry strips. The five CI/node triggers were reachable as a planner step, and
`github_trigger_workflow` was not even in `_DEFAULT_TOOLS_DENY`, so it ran under shipped defaults.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from raven.core.agent.agent import Agent
from raven.core.agents.orchestrator import AgentContext, AgentOrchestrator
from raven.core.agents.profiles import resolve_profile
from raven.core.config import settings
from raven.core.llm import LLMResponse, ToolCall
from raven.core.models import PluginTool, Session
from raven.core.plugin_loader import PluginLoader
from raven.core.security.tool_policy import (
    EXEC_CLASS_TOKENS,
    ExecAskMode,
    ExecSecurity,
    ToolPolicyEvaluator,
    is_exec_class,
)
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.register_all import create_task_tool_registry, create_tool_registry

ROOT = Path(__file__).resolve().parents[1]
RAN: list[str] = []
_PARAMS = {"text": {"type": "string"}}

REGISTRY_TRIGGERS = (
    "nodes_exec",
    "ci_run_workflow",
    "ci_trigger_pipeline",
    "ci_jenkins_job",
    "github_trigger_workflow",
)
PLUGIN_BYPASSES = (
    "process.run",
    "process.kill",
    "memory.run_code_and_remember",
    "api.http_put",
    "api.http_delete",
    "browser.browse",
)
TWIN_PAIRS = (
    ("process.kill", "process_kill"),
    ("process.run", "process_run"),
    ("api.http_post", "http_post"),
    ("api.http_put", "http_put"),
    ("git.git_push", "git_push"),
    ("browser.search", "browser_search"),
)
# the description sweep's reviewed exemptions, each with the reason it is not exec-class
# wave #88 reworded the two sessions tools so they no longer start with send/spawn: they write rows,
# and the descriptions say so.
UNGATED_BY_REVIEW = {
    "run_tests": "the pytest runner bounds extra_args (_sanitize_extra_args) and reviewer/qa/security rely on it",
    "test_coverage": "the same bounded runner with --cov",
    "notify": "delivery to the operator's own channel, not third-party egress",
    "dream_cycle": "memory consolidation over the local store",
}
GIT_VERB_PHRASE = "the git mutating verbs"


def _probe(name: str) -> Callable[..., Any]:
    def _handler(**kwargs: Any) -> str:
        RAN.append(name)
        return f"ran:{name}"

    return _handler


def _registry_with(*names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(
            ToolSpec(
                name=name,
                description=f"exec class probe {name}",
                parameters=_PARAMS,
                handler=_probe(name),
                category="test",
            )
        )
    return registry


def _inverted(real: ToolRegistry) -> ToolRegistry:
    """Every real tool name with an inert handler: the offer can be measured without running anything."""
    registry = ToolRegistry()
    for spec in real.list():
        registry.register(
            ToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=_PARAMS,
                handler=_probe(spec.name),
                category="test",
            )
        )
    return registry


def _policy(
    exec_security: ExecSecurity = ExecSecurity.FULL,
    exec_ask: ExecAskMode = ExecAskMode.OFF,
    profile: str = "full",
) -> ToolPolicyEvaluator:
    return ToolPolicyEvaluator(
        profile=profile,
        deny=[],
        allow=[],
        exec_security=exec_security,
        exec_ask=exec_ask,
        workspace_only=False,
    )


class _FakeLLM:
    async def complete(
        self, messages: list[dict[str, Any]], tools: Any = None, model: str | None = None
    ) -> LLMResponse:
        return LLMResponse(content="done")


def _orchestrator(registry: ToolRegistry, policy: ToolPolicyEvaluator) -> AgentOrchestrator:
    return AgentOrchestrator(
        llm=_FakeLLM(),  # type: ignore[arg-type]
        tool_registry=registry,
        tool_policy=policy,
        planner_enabled=False,
        critic_enabled=False,
        reflect_enabled=False,
    )


def _ctx() -> AgentContext:
    return AgentContext(query="probe")


@pytest.fixture(scope="module")
def name_space() -> dict[str, Any]:
    loader = PluginLoader()
    for plugin_dir in sorted((ROOT / "raven" / "plugins").iterdir()):
        if plugin_dir.is_dir() and plugin_dir.name != "__pycache__":
            loader.load_from_dir(plugin_dir)
    registry = create_tool_registry()
    return {
        "registry": registry,
        "registry_names": {s.name for s in registry.list()},
        "plugin_names": {t.name for t in loader.tools},
        "specs": [(s.name, s.description) for s in registry.list()] + [(t.name, t.description) for t in loader.tools],
    }


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    RAN.clear()
    monkeypatch.setattr(settings, "tools_deny", "")
    monkeypatch.setattr(settings, "tools_allow", "")
    monkeypatch.setattr(settings, "exec_security", "deny")
    monkeypatch.setattr(settings, "exec_ask_mode", "always")
    monkeypatch.setattr(settings, "workspace_only", False)


def _offered(orch: AgentOrchestrator) -> set[str]:
    # debugger: allowed_tools == ["*"], denied_tools == [] — the offer must show the exec gate, not
    # the profile gate, and coder denies shell/python by name.
    schemas = orch._build_tool_schemas(resolve_profile("debugger"))
    if schemas is None:
        return set()
    return {s["function"]["name"] for s in schemas}


def _reachable_names(space: dict[str, Any]) -> set[str]:
    """The two shipped name spaces plus the form the MCP bridge gives server tools."""
    registry: set[str] = space["registry_names"]
    plugin: set[str] = space["plugin_names"]
    return registry | plugin | {"mcp_github_get_issue"}


# --- the separator rule -------------------------------------------------------------------


def test_classification_does_not_depend_on_the_namespace_separator(name_space: dict[str, Any]) -> None:
    for name in _reachable_names(name_space):
        assert is_exec_class(name) == is_exec_class(name.replace(".", "_")), name


@pytest.mark.parametrize(("dotted", "bare"), TWIN_PAIRS)
def test_a_namespaced_twin_is_classified_like_the_registry_name(dotted: str, bare: str) -> None:
    assert is_exec_class(dotted) == is_exec_class(bare), (dotted, bare)


def test_the_source_normalizes_separators() -> None:
    tree = ast.parse((ROOT / "raven" / "core" / "security" / "tool_policy.py").read_text(encoding="utf-8"))
    body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "is_exec_class")
    # ast.unparse re-quotes, so match the call rather than the literal spelling
    assert re.search(r"""replace\(\s*['"]\.['"]\s*,\s*['"]_['"]\s*\)""", ast.unparse(body)), ast.unparse(body)


# --- the tokens themselves -----------------------------------------------------------------


@pytest.mark.parametrize("name", REGISTRY_TRIGGERS)
def test_a_registry_name_that_runs_something_remote_is_exec_class(name: str) -> None:
    assert is_exec_class(name), name


@pytest.mark.parametrize("name", PLUGIN_BYPASSES)
def test_the_capability_reachable_under_a_dotted_name_is_exec_class(name: str) -> None:
    assert is_exec_class(name), name


def test_no_token_matches_nothing(name_space: dict[str, Any]) -> None:
    reachable = _reachable_names(name_space)
    dead = [t for t in EXEC_CLASS_TOKENS if not any(t in n.replace(".", "_") for n in reachable)]
    assert dead == [], dead


def test_the_node_token_that_matched_nothing_is_gone() -> None:
    assert "node_" not in EXEC_CLASS_TOKENS
    assert is_exec_class("nodes_exec")


def test_the_mcp_prefix_is_live_because_the_bridge_builds_that_name() -> None:
    src = (ROOT / "raven" / "core" / "gateway" / "mcp_bridge.py").read_text(encoding="utf-8")
    assert 'f"mcp_{name}_{raw_name}"' in src, "server tools no longer carry the mcp_ prefix"
    assert is_exec_class("mcp_github_get_issue")


def test_memory_run_python_stays_gated_although_the_loader_no_longer_publishes_it(
    name_space: dict[str, Any],
) -> None:
    """Wave #87 gated this name while it was an accident of the loader; wave #88 removed the accident.

    The memory plugin imported the code plugin's run_python and the loader published the import as
    memory.run_python. It is no longer on the surface, but the name must stay exec-class: a plugin
    that defines or re-exports it still reaches the gate, and the import itself is still used inside
    memory.run_code_and_remember.
    """
    assert "memory.run_python" not in name_space["plugin_names"]
    assert "memory.run_code_and_remember" in name_space["plugin_names"]
    src = (ROOT / "raven" / "plugins" / "memory" / "plugin.py").read_text(encoding="utf-8")
    assert "await code_run_python(code)" in src, "the wiring no longer holds"
    assert is_exec_class("memory.run_python") and is_exec_class("memory.run_code_and_remember")


# --- what the classification buys -----------------------------------------------------------


@pytest.mark.parametrize("name", REGISTRY_TRIGGERS)
def test_the_remote_triggers_are_stripped_from_the_planner_registry(name: str) -> None:
    full = {s.name for s in create_tool_registry().list()}
    task = {s.name for s in create_task_tool_registry().list()}
    assert name in full
    assert name not in task, f"{name} is a step a planner can author"


async def test_calling_the_dotted_twin_is_now_refused(shipped: None) -> None:
    # api.http_put rather than process.run: policy/tools.json denies process.run, and is_tool_allowed
    # consults that ruleset only after something else has loaded it into the policy_engine singleton, so
    # a probe on a denied name would measure the ruleset instead of the exec level.
    orch = _orchestrator(_registry_with("api.http_put"), _policy(ExecSecurity.DENY))
    result = await orch._execute_tool_safe(
        ToolCall(id="1", name="api.http_put", arguments={"text": "hi"}), resolve_profile("debugger"), _ctx()
    )
    assert RAN == []
    assert "error" in result


async def test_the_same_call_runs_once_the_operator_raises_the_level(shipped: None) -> None:
    orch = _orchestrator(_registry_with("api.http_put"), _policy(ExecSecurity.FULL))
    result = await orch._execute_tool_safe(
        ToolCall(id="1", name="api.http_put", arguments={"text": "hi"}), resolve_profile("debugger"), _ctx()
    )
    assert RAN == ["api.http_put"], result
    assert "error" not in result


# --- the offer follows the gate ---------------------------------------------------------------


def test_deny_mode_keeps_exec_tools_out_of_the_offer(shipped: None, name_space: dict[str, Any]) -> None:
    orch = _orchestrator(_inverted(name_space["registry"]), _policy(ExecSecurity.DENY))
    offered = _offered(orch)
    assert offered, "the offer went empty, which is not the point of the filter"
    assert not [n for n in offered if is_exec_class(n)], sorted(offered)[:10]


def test_full_mode_still_offers_them(shipped: None, name_space: dict[str, Any]) -> None:
    orch = _orchestrator(_inverted(name_space["registry"]), _policy(ExecSecurity.FULL))
    offered = _offered(orch)
    assert "shell" in offered and "python" in offered, sorted(offered)[:10]


def test_ask_mode_offers_them_because_confirmation_is_a_per_call_question(
    shipped: None, name_space: dict[str, Any]
) -> None:
    orch = _orchestrator(_inverted(name_space["registry"]), _policy(ExecSecurity.ASK, ExecAskMode.ALWAYS))
    assert "shell" in _offered(orch)


MESSAGING_OFFER = ("files.read", "api.http_get", "memory.recall", "browser.search")


def _plugin_tools(*names: str) -> list[PluginTool]:
    return [
        PluginTool(name=n, description=f"probe {n}", parameters={"type": "object"}, handler=_probe(n)) for n in names
    ]


def _agent(policy: ToolPolicyEvaluator, *names: str) -> Agent:
    return Agent(
        session=Session(id="exec-class-probe", channel="telegram", user_id="user1"),
        tools=_plugin_tools(*names),
        db=MagicMock(),
        llm=MagicMock(),
        tool_policy=policy,
    )


def test_the_agent_offer_drops_the_exec_tool_the_messaging_profile_declares(shipped: None) -> None:
    agent = _agent(_policy(ExecSecurity.DENY, profile="messaging"), *MESSAGING_OFFER)
    offered = {s["function"]["name"] for s in agent._tool_schemas()}
    assert offered == {"files.read", "api.http_get", "memory.recall"}, offered


def test_raising_the_level_gives_search_back(shipped: None) -> None:
    agent = _agent(_policy(ExecSecurity.FULL, profile="messaging"), *MESSAGING_OFFER)
    offered = {s["function"]["name"] for s in agent._tool_schemas()}
    assert "browser.search" in offered, offered


def test_both_offer_builders_consult_the_level() -> None:
    for rel, fn in (
        ("raven/core/agents/orchestrator.py", "_build_tool_schemas"),
        ("raven/core/agent/agent.py", "_tool_schemas"),
    ):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
        src = ast.unparse(body)
        assert "ExecSecurity.DENY" in src and "is_exec_class" in src, (rel, fn, src[:200])


# --- drift gates over the real registry --------------------------------------------------------


def test_no_described_execution_stays_ungated(name_space: dict[str, Any]) -> None:
    verbs = ("execute", "run ", "trigger", "dispatch", "kill", "spawn", "send", "deploy", "invoke")
    described = [(n, d) for n, d in name_space["specs"] if d.lower().startswith(verbs)]
    gated = [n for n, _ in described if is_exec_class(n)]
    missing = sorted(n for n, _ in described if not is_exec_class(n))
    assert len(gated) >= 15, gated
    assert missing == sorted(UNGATED_BY_REVIEW), missing


@pytest.mark.parametrize("name", sorted(UNGATED_BY_REVIEW))
def test_each_exemption_is_still_a_real_tool(name: str, name_space: dict[str, Any]) -> None:
    """An exemption for a name that no longer exists would hide the next unclassified tool."""
    assert name in {n for n, _ in name_space["specs"]}, name


def test_the_documented_families_name_every_token() -> None:
    doc = (ROOT / "docs" / "security" / "overview.md").read_text(encoding="utf-8")
    block = next(b for b in doc.split("\n## ") if "EXEC_CLASS_TOKENS" in b)
    git_verbs = [t for t in EXEC_CLASS_TOKENS if t.startswith("git_")]
    for token in EXEC_CLASS_TOKENS:
        if token in git_verbs:
            continue
        assert token in block, token
    assert GIT_VERB_PHRASE in block, "the git verbs must stay documented, not silently dropped"


def test_the_mcp_doc_counts_the_tools_this_gate_serves() -> None:
    from ravencode.runtime.tools import MODULE_TOOLS

    count = len([n for n in MODULE_TOOLS if is_exec_class(n)])
    doc = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
    assert f"the {count} exec-class tools" in doc, (count, re.findall(r"the \d+ exec-class tools", doc))


def test_the_configuration_table_still_lists_the_surfaces() -> None:
    lines = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8").splitlines()
    row = next(line for line in lines if line.startswith("| `EXEC_SECURITY`"))
    for surface in ("agent path", "orchestrator", "task steps", "MCP"):
        assert surface in row, (surface, row)
    assert "CI/workflow triggers" in row and "sandbox code" in row, row
