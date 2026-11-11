from __future__ import annotations

import ast
import dataclasses
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from raven.core.agents.orchestrator import _IMPLEMENT_TOOLS, AgentContext, AgentOrchestrator
from raven.core.agents.profiles import PROFILES, AgentProfile, resolve_profile
from raven.core.config import settings
from raven.core.llm import LLMResponse, ToolCall
from raven.core.security.tool_policy import ExecAskMode, ExecSecurity, ToolPolicyEvaluator
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.register_all import create_tool_registry

ROOT = Path(__file__).resolve().parents[1]
RAN: list[str] = []
_PARAMS = {"text": {"type": "string"}}


def _probe(name: str) -> Callable[..., Any]:
    def _handler(**kwargs: Any) -> str:
        RAN.append(name)
        return f"ran:{name}"

    return _handler


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"profile gate probe {name}",
        parameters=_PARAMS,
        handler=_probe(name),
        category="test",
    )


def _inverted(real: ToolRegistry) -> ToolRegistry:
    """Every real tool name, but an inert handler: the gate can be walked without running anything."""
    registry = ToolRegistry()
    for spec in real.list():
        registry.register(_spec(spec.name))
    return registry


def _permissive() -> ToolPolicyEvaluator:
    return ToolPolicyEvaluator(
        profile="full",
        deny=[],
        allow=[],
        exec_security=ExecSecurity.FULL,
        exec_ask=ExecAskMode.OFF,
        workspace_only=False,
    )


class _FakeLLM:
    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])

    async def complete(
        self, messages: list[dict[str, Any]], tools: Any = None, model: str | None = None
    ) -> LLMResponse:
        return self._responses.pop(0) if self._responses else LLMResponse(content="done")


def _orchestrator(registry: ToolRegistry, **kwargs: Any) -> AgentOrchestrator:
    return AgentOrchestrator(
        llm=kwargs.pop("llm", _FakeLLM()),
        tool_registry=registry,
        planner_enabled=False,
        critic_enabled=False,
        reflect_enabled=False,
        **kwargs,
    )


def _real() -> ToolRegistry:
    return create_tool_registry()


@pytest.fixture
def shipped_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    # The built-in deny list is what the tests below measure, so a local .env cannot widen it.
    monkeypatch.setattr(settings, "tools_deny", "")
    monkeypatch.setattr(settings, "tools_allow", "")


def _registry_names(registry: ToolRegistry) -> set[str]:
    return {s.name for s in registry.list()}


def _offered(orch: AgentOrchestrator, profile: AgentProfile) -> set[str]:
    schemas = orch._build_tool_schemas(profile)
    if schemas is None:
        return set()
    return {s["function"]["name"] for s in schemas}


def _profile_named(name: str) -> str:
    return f"not allowed by profile '{name}'"


@pytest.fixture
def ran_clean(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    RAN.clear()
    return RAN


# --- the names the profiles speak must be the names the registry answers -------------------------


def test_every_profile_tool_name_names_a_real_tool() -> None:
    real = _registry_names(_real())
    ghosts = {n for p in PROFILES.values() for n in (*p.allowed_tools, *p.denied_tools) if n != "*" and n not in real}
    assert not ghosts, f"profiles name tools no surface serves: {sorted(ghosts)}"


def test_implement_tools_all_name_real_tools() -> None:
    real = _registry_names(_real())
    assert real >= _IMPLEMENT_TOOLS, f"unreachable in the plan tracker: {sorted(_IMPLEMENT_TOOLS - real)}"


def test_the_handoff_set_is_the_profile_registry() -> None:
    from raven.core.agents import orchestrator as mod

    assert frozenset(PROFILES) | {"done"} == mod._VALID_HANDOFF_PROFILES
    assert "done" in mod._VALID_HANDOFF_PROFILES
    assert len(mod._VALID_HANDOFF_PROFILES) == len(PROFILES) + 1


def test_every_profile_is_named_in_the_handoff_prompt() -> None:
    from raven.core.agents.orchestrator import _NEXT_AGENT_PROMPT

    missing = {n for n in PROFILES if f"**{n}**" not in _NEXT_AGENT_PROMPT}
    assert not missing, f"the coordinator is never told these profiles exist: {sorted(missing)}"


# --- the offer and the call are one rule ---------------------------------------------------------


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
async def test_the_offer_and_the_gate_admit_the_same_tools(profile_name: str, ran_clean: list[str]) -> None:
    profile = PROFILES[profile_name]
    orch = _orchestrator(_inverted(_real()), tool_policy=_permissive())
    offered = _offered(orch, profile)
    refused: set[str] = set()
    for name in sorted(_registry_names(_real())):
        call = ToolCall(id="1", name=name, arguments={"text": "x"})
        out = await orch._execute_tool_safe(call, profile, AgentContext(query="probe"))
        if _profile_named(profile_name) in str(out.get("error", "")):
            refused.add(name)
    assert offered == set(_registry_names(_real())) - refused, "offer and call diverged"
    assert set(ran_clean) == offered, "what ran is not what was offered"


async def test_a_tool_the_profile_does_not_declare_never_reaches_its_handler(ran_clean: list[str]) -> None:
    orch = _orchestrator(_inverted(_real()), tool_policy=_permissive())
    planner = PROFILES["planner"]
    assert "knowledge_stats" not in planner.allowed_tools
    out = await orch._execute_tool_safe(
        ToolCall(id="1", name="knowledge_stats", arguments={"text": "x"}), planner, AgentContext(query="probe")
    )
    assert "knowledge_stats" not in ran_clean
    assert _profile_named("planner") in str(out.get("error", ""))


async def test_a_declared_tool_still_runs(ran_clean: list[str]) -> None:
    orch = _orchestrator(_inverted(_real()), tool_policy=_permissive())
    planner = PROFILES["planner"]
    assert "file_read" in planner.allowed_tools
    out = await orch._execute_tool_safe(
        ToolCall(id="1", name="file_read", arguments={"text": "x"}), planner, AgentContext(query="probe")
    )
    assert ran_clean == ["file_read"]
    assert "error" not in out


async def test_the_coder_deny_list_is_honoured_at_call_time(ran_clean: list[str]) -> None:
    orch = _orchestrator(_inverted(_real()), tool_policy=_permissive())
    coder = PROFILES["coder"]
    for name in coder.denied_tools:
        out = await orch._execute_tool_safe(
            ToolCall(id="1", name=name, arguments={"text": "x"}), coder, AgentContext(query="probe")
        )
        assert _profile_named("coder") in str(out.get("error", "")), name
    assert not ran_clean


def test_a_star_in_denied_tools_refuses_everything() -> None:
    # The branch this replaces treated "*" in denied_tools as "allow everything instead".
    profile = AgentProfile(
        name="blanket",
        display_name="Blanket",
        role="blanket",
        system_prompt="x",
        allowed_tools=["*"],
        denied_tools=["*"],
    )
    assert not profile.allows_tool("file_read")
    orch = _orchestrator(_inverted(_real()))
    assert _offered(orch, profile) == set()


def test_the_denied_name_wins_over_the_allowed_name() -> None:
    profile = AgentProfile(
        name="both",
        display_name="Both",
        role="both",
        system_prompt="x",
        allowed_tools=["file_read", "shell"],
        denied_tools=["shell"],
    )
    assert profile.allows_tool("file_read")
    assert not profile.allows_tool("shell")


# --- what the shipped operator defaults do to the offer -----------------------------------------


async def test_the_shipped_defaults_do_not_offer_a_denied_tool(shipped_switches: None) -> None:
    orch = _orchestrator(_inverted(_real()))
    assert not orch._tool_policy.is_tool_allowed("shell")
    assert "shell" not in _offered(orch, PROFILES["reviewer"])
    assert "file_read" in _offered(orch, PROFILES["reviewer"])


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_profile_is_offered_a_working_set(profile_name: str, shipped_switches: None) -> None:
    orch = _orchestrator(_inverted(_real()))
    offered = _offered(orch, PROFILES[profile_name])
    assert len(offered) >= 5, f"{profile_name} would run with {len(offered)} tools"


# --- handoff only reaches the targets a profile declares -----------------------------------------


def _handoff_orch(targets: list[str]) -> tuple[AgentOrchestrator, AgentProfile]:
    # A copy: PROFILES holds one shared instance per name and a test must not edit it.
    profile = dataclasses.replace(PROFILES["architect"], handoff_profiles=targets)
    return _orchestrator(_inverted(_real())), profile


async def test_a_declared_handoff_target_is_taken() -> None:
    orch, profile = _handoff_orch(["coder", "planner"])
    orch._decide_next_agent = lambda messages, current: _ago("coder")  # type: ignore[method-assign,assignment]
    nxt = await orch._maybe_handoff([], profile, 0)
    assert nxt is not None and nxt.name == "coder"


async def test_an_undeclared_handoff_target_is_refused() -> None:
    orch, profile = _handoff_orch(["coder", "planner"])
    orch._decide_next_agent = lambda messages, current: _ago("security")  # type: ignore[method-assign,assignment]
    assert await orch._maybe_handoff([], profile, 0) is None


async def test_an_empty_handoff_list_hands_off_to_nobody() -> None:
    orch, profile = _handoff_orch([])
    orch._decide_next_agent = lambda messages, current: _ago("coder")  # type: ignore[method-assign,assignment]
    assert await orch._maybe_handoff([], profile, 0) is None


async def _ago(value: str) -> str:
    return value


# --- the fields that had no consumer are gone, and the scan proves it ----------------------------


def _dead_terms() -> list[str]:
    # Built in pieces: a literal here would make the tree-wide scan find itself.
    return [
        "".join(["allowed_tool", "_categories"]),
        "".join(["model", "_preference"]),
        "".join(["context", "_limit"]),
        "".join(["get_tools", "_for_profile"]),
    ]


def test_the_unread_profile_fields_stay_gone() -> None:
    fields = {f.name for f in dataclasses.fields(AgentProfile)}
    dead = set(_dead_terms())
    assert not fields & dead, f"declared again with no consumer: {sorted(fields & dead)}"
    assert {"allowed_tools", "denied_tools", "handoff_profiles", "can_handoff"} <= fields


def test_the_dead_names_have_no_reference_left_anywhere() -> None:
    pattern = re.compile("|".join(_dead_terms()))
    hits: list[str] = []
    for base in ("raven", "ravencode", "aios", "scripts", "docs"):
        for path in (ROOT / base).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md"}:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"references to deleted profile fields remain: {hits}"
    # Non-vacuity: the same scan finds a field that is still live.
    live = re.compile("|".join(["allowed_to", "ols"]))
    assert live.search((ROOT / "raven/core/agents/profiles.py").read_text(encoding="utf-8"))


def test_the_helper_that_duplicated_the_schema_filter_is_gone() -> None:
    source = (ROOT / "raven/core/agents/orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    bodies = {n.name: ast.dump(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    assert "profile.denied_tools" not in bodies["_execute_tool_safe"]
    assert "allows_tool" in bodies["_execute_tool_safe"]
    assert "allows_tool" in bodies["_build_tool_schemas"]


def test_resolve_profile_still_falls_back_to_coder() -> None:
    assert resolve_profile("no-such-profile").name == "coder"
