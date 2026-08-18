from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ravencode.agents import custom_agents as ca
from ravencode.agents import multi as multi_mod
from ravencode.agents import orchestrator as orch
from ravencode.agents.custom_agents import CustomAgentDef
from ravencode.agents.multi import MultiAgentOrchestrator, SubTask, TaskResult, get_multi_orchestrator
from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator
from ravencode.config.loader import RavenConfig
from ravencode.runtime.agent_core import AgentConfig

# ---------------------------------------------------------------------------
# custom_agents
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_custom_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ca, "_custom_agents", None)


def test_custom_agent_def_defaults() -> None:
    d = CustomAgentDef("researcher", {})
    assert d.name == "researcher"
    assert d.system_prompt == ""
    assert d.max_steps == 30
    assert d.confirm_dangerous is True
    assert d.diff_preview is True
    assert d.proactive_scan is True
    assert d.tools is None
    assert d.restricted_tools == []
    assert d.description == ""


def test_custom_agent_def_values() -> None:
    d = CustomAgentDef(
        "coder",
        {
            "system_prompt": "sp",
            "max_steps": 10,
            "confirm_dangerous": False,
            "diff_preview": False,
            "proactive_scan": False,
            "tools": ["read", "grep"],
            "restricted_tools": ["bash"],
            "description": "desc",
        },
    )
    assert d.system_prompt == "sp"
    assert d.max_steps == 10
    assert d.confirm_dangerous is False
    assert d.diff_preview is False
    assert d.proactive_scan is False
    assert d.tools == ["read", "grep"]
    assert d.restricted_tools == ["bash"]
    assert d.description == "desc"


def test_custom_agent_def_to_dict() -> None:
    d = CustomAgentDef("n", {"system_prompt": "sp", "tools": ["read"]})
    payload = d.to_dict()
    assert payload["name"] == "n"
    assert payload["system_prompt"] == "sp"
    assert payload["tools"] == ["read"]
    assert payload["max_steps"] == 30


def test_load_agents_config_explicit_path(tmp_path: Path) -> None:
    cfg_file = tmp_path / "agents.json"
    cfg_file.write_text(
        json.dumps({"agents": {"researcher": {"system_prompt": "sp", "max_steps": 5}}}),
        encoding="utf-8",
    )
    agents = ca.load_agents_config(str(cfg_file))
    assert set(agents) == {"researcher"}
    assert agents["researcher"].max_steps == 5


def test_load_agents_config_finds_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "ravencode" / "agents"
    target.mkdir(parents=True)
    (target / "custom_agents.json").write_text(json.dumps({"agents": {"a": {}}}), encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    agents = ca.load_agents_config()
    assert set(agents) == {"a"}


def test_load_agents_config_finds_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".config" / "raven"
    target.mkdir(parents=True)
    (target / "custom_agents.json").write_text(json.dumps({"agents": {"b": {}}}), encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    agents = ca.load_agents_config()
    assert set(agents) == {"b"}


def test_load_agents_config_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "agents.json"
    cfg_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nope_cwd")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nope_home")
    assert ca.load_agents_config(str(cfg_file)) == {}


def test_load_agents_config_missing_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: Path("does_not_exist_dir_xyz"))
    monkeypatch.setattr(Path, "home", lambda: Path("does_not_exist_home_xyz"))
    assert ca.load_agents_config() == {}


def test_get_and_reload_custom_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    first = {"a": CustomAgentDef("a", {})}
    second = {"b": CustomAgentDef("b", {})}
    loader = Mock(side_effect=[first, second])
    monkeypatch.setattr(ca, "load_agents_config", loader)
    assert ca.get_custom_agents() == first
    assert ca.get_custom_agents() == first
    assert loader.call_count == 1
    assert ca.reload_custom_agents() == second
    assert loader.call_count == 2


# ---------------------------------------------------------------------------
# multi-agent
# ---------------------------------------------------------------------------


def test_subtask_defaults() -> None:
    t = SubTask("do it")
    assert t.agent_type == AgentType.AUTONOMOUS
    assert t.depends_on is None
    assert t.config is None


def _make_result(task: str) -> AgentResult:
    return AgentResult(agent="autonomous", success=True, data={"result": task})


def _make_orchestrator(monkeypatch: pytest.MonkeyPatch) -> tuple[MultiAgentOrchestrator, AsyncMock]:
    m = MultiAgentOrchestrator()
    dispatch = AsyncMock(side_effect=lambda task, agent_type, **kw: _make_result(task))
    monkeypatch.setattr(m._orchestrator, "dispatch", dispatch)
    return m, dispatch


@pytest.mark.asyncio
async def test_run_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    m, dispatch = _make_orchestrator(monkeypatch)
    results = await m.run_sequential([SubTask("one"), SubTask("two", agent_type=AgentType.CODER)])
    assert [r.index for r in results] == [0, 1]
    assert [r.description for r in results] == ["one", "two"]
    assert results[0].result.data == {"result": "one"}
    assert dispatch.await_count == 2
    assert dispatch.await_args_list[1].args[1] == AgentType.CODER


@pytest.mark.asyncio
async def test_run_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    m, dispatch = _make_orchestrator(monkeypatch)
    results = await m.run_parallel([SubTask("a"), SubTask("b"), SubTask("c")], max_concurrent=2)
    assert len(results) == 3
    assert [r.index for r in results] == [0, 1, 2]
    assert dispatch.await_count == 3


@pytest.mark.asyncio
async def test_run_dag_topological_order(monkeypatch: pytest.MonkeyPatch) -> None:
    m, dispatch = _make_orchestrator(monkeypatch)
    tasks = [SubTask("A"), SubTask("B", depends_on=[0]), SubTask("C", depends_on=[1])]
    results = await m.run_dag(tasks)
    assert [r.index for r in results] == [0, 1, 2]
    order = [call.args[0] for call in dispatch.await_args_list]
    assert order == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_run_dag_circular_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    m, _ = _make_orchestrator(monkeypatch)
    tasks = [SubTask("A", depends_on=[1]), SubTask("B", depends_on=[0])]
    with pytest.raises(RuntimeError, match="Circular dependency"):
        await m.run_dag(tasks)


@pytest.mark.asyncio
async def test_run_dag_config_override_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    m, dispatch = _make_orchestrator(monkeypatch)
    cfg = AgentConfig(max_steps=5)
    await m.run_dag([SubTask("A", config=cfg)])
    assert dispatch.await_args_list[0].kwargs.get("agent_config_override") is cfg


def test_multi_orchestrator_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(multi_mod, "_orchestrator_instance", None)
    first = get_multi_orchestrator()
    second = get_multi_orchestrator()
    assert first is second


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, config: object = None, conversation: object = None) -> None:
        self.config = config
        self.conversation = conversation or SimpleNamespace(message_count=2)
        self.task: str = ""

    async def run(self, task: str) -> str:
        self.task = task
        return "done"


@pytest.fixture(autouse=True)
def _patch_agent(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(orch, "ReActAgent", _FakeAgent)
    monkeypatch.setattr(orch, "Conversation", lambda system_prompt=None: SimpleNamespace(system_prompt=system_prompt, message_count=2))
    yield


def _fake_cfg() -> RavenConfig:
    return RavenConfig(
        max_steps=20,
        plan_mode=False,
        auto_format=True,
        use_cache=False,
        confirm_dangerous=True,
        diff_preview=True,
        proactive_scan=False,
    )


def test_build_agent_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    def _rec(**kw: object) -> object:
        captured.append(kw)
        return object()

    monkeypatch.setattr(orch, "AgentConfig", _rec)
    orch.Orchestrator._build_agent(
        system_prompt="SP",
        max_steps=7,
        memory_path="/mem",
        raven_config=_fake_cfg(),
    )
    assert len(captured) == 1
    cfg = captured[0]
    assert cfg["memory_path"] == "/mem"
    assert cfg["max_steps"] == 7
    assert cfg["plan_mode"] is False
    assert cfg["auto_format"] is True
    assert cfg["use_cache"] is False
    assert cfg["confirm_dangerous"] is True
    assert cfg["diff_preview"] is True
    assert cfg["proactive_scan"] is False
    assert cfg["permissions"] is None


def test_build_agent_with_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "PermissionManager", SimpleNamespace(from_dict=Mock(return_value="pm")))
    captured: list[dict[str, object]] = []

    def _rec(**kw: object) -> object:
        captured.append(kw)
        return object()

    monkeypatch.setattr(orch, "AgentConfig", _rec)
    cfg = _fake_cfg()
    cfg.permissions = [{"rules": []}]
    orch.Orchestrator._build_agent(raven_config=cfg)
    assert captured[0]["permissions"] == "pm"


def test_build_agent_uses_get_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "get_config", Mock(return_value=_fake_cfg()))
    captured: list[dict[str, object]] = []

    def _rec(**kw: object) -> object:
        captured.append(kw)
        return object()

    monkeypatch.setattr(orch, "AgentConfig", _rec)
    orch.Orchestrator._build_agent()
    assert captured[0]["max_steps"] == 20


def test_build_with_override(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AgentConfig(max_steps=3)
    agent = orch.Orchestrator._build_with_override(cfg, system_prompt="SP")
    assert isinstance(agent, _FakeAgent)
    assert agent.config is cfg
    assert agent.conversation.system_prompt == "SP"


def test_build_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "get_config", Mock(return_value=_fake_cfg()))
    agent = orch.Orchestrator._build_with_override(None, system_prompt="SP")
    assert isinstance(agent, _FakeAgent)
    assert agent.conversation.system_prompt == "SP"


@pytest.mark.asyncio
async def test_dispatch_unknown_agent() -> None:
    result = await Orchestrator().dispatch("x", "bogus")  # type: ignore[arg-type]
    assert result.success is False
    assert result.error == "Unknown agent: bogus"
    assert result.agent == "bogus"


@pytest.mark.asyncio
async def test_dispatch_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="PLANNER"))
    result = await Orchestrator().dispatch("plan", AgentType.PLANNER)
    assert result.success is True
    assert result.agent == "planner"
    assert result.data == {"plan": "done"}
    assert result.steps == 2


@pytest.mark.asyncio
async def test_dispatch_planner_readonly_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="PRO"))
    result = await Orchestrator().dispatch("plan", AgentType.PLANNER_READONLY)
    assert result.success is True
    assert result.agent == "planner_readonly"
    assert result.data == {"plan": "done"}


@pytest.mark.asyncio
async def test_dispatch_planner_readonly_with_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="PRO"))
    cfg = AgentConfig(plan_mode=True)
    result = await Orchestrator().dispatch(
        "plan", AgentType.PLANNER_READONLY, agent_config_override=cfg
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_dispatch_coder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="CODER"))
    result = await Orchestrator().dispatch(
        "code", AgentType.CODER, agent_config_override=AgentConfig()
    )
    assert result.success is True
    assert result.agent == "coder"
    assert result.data == {"code_result": "done"}
    assert result.steps == 2


@pytest.mark.asyncio
async def test_dispatch_debugger_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="DEBUG"))
    result = await Orchestrator().dispatch("debug", AgentType.DEBUGGER)
    assert result.success is True
    assert result.agent == "debugger"
    assert result.data == {"debug_result": "done"}


@pytest.mark.asyncio
async def test_dispatch_debugger_with_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="DEBUG"))
    cfg = AgentConfig()
    result = await Orchestrator().dispatch("debug", AgentType.DEBUGGER, agent_config_override=cfg)
    assert result.success is True


@pytest.mark.asyncio
async def test_dispatch_autonomous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "get_config", Mock(return_value=_fake_cfg()))
    result = await Orchestrator().dispatch("auto", AgentType.AUTONOMOUS)
    assert result.success is True
    assert result.agent == "autonomous"
    assert result.data == {"result": "done"}
    assert result.steps == 2


@pytest.mark.asyncio
async def test_dispatch_catches_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="PLANNER"))

    class _BoomAgent:
        def __init__(self, config: object = None, conversation: object = None) -> None:
            pass

        async def run(self, task: str) -> str:
            raise RuntimeError("agent exploded")

    monkeypatch.setattr(orch, "ReActAgent", _BoomAgent)
    result = await Orchestrator().dispatch(
        "plan", AgentType.PLANNER, agent_config_override=AgentConfig()
    )
    assert result.success is False
    assert result.error == "agent exploded"


@pytest.mark.asyncio
async def test_delegate_static(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.agents.orchestrator.get_prompt", Mock(return_value="DELEGATE"))
    out = await Orchestrator.delegate("sub", context="ctx")
    assert out == "done"
