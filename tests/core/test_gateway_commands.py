from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.agents import PROFILES
from raven.core.auth import Permission
from raven.core.gateway.commands.agent import AgentCommand, AgentStatusCommand
from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.gateway.commands.compact import CompactCommand
from raven.core.gateway.commands.help import HelpCommand
from raven.core.gateway.commands.mcp import MCPCommand
from raven.core.gateway.commands.new_session import NewSessionCommand
from raven.core.gateway.commands.registry import CommandRegistry
from raven.core.gateway.commands.reset import ResetCommand
from raven.core.gateway.commands.settings import (
    ActivationCommand,
    RestartCommand,
    ThinkCommand,
    TraceCommand,
    UsageCommand,
    VerboseCommand,
)
from raven.core.gateway.commands.skills import SkillsCommand
from raven.core.gateway.commands.status import StatusCommand
from raven.core.gateway.commands.task import TaskCommand
from raven.core.models import IncomingMessage
from raven.core.skills import skills_registry


class _FakeGateway:
    def __init__(self) -> None:
        self._send = AsyncMock()
        self.db = SimpleNamespace(delete_session=AsyncMock())
        self.channels = SimpleNamespace(list_ids=AsyncMock(return_value=[]))
        self.registry = SimpleNamespace(list_agents=lambda: [])
        self.mcp = SimpleNamespace(connected_count=0, list_servers_info=lambda: [])
        self._artifact_root: str | None = None
        self.set_pref = MagicMock()
        self.get_pref = MagicMock(return_value="off")
        self._check_permission = MagicMock(return_value=True)
        self._bg_task = AsyncMock()
        self.tasks = SimpleNamespace(create_and_run=MagicMock(return_value="coro"))


def _ctx(
    channel: str = "tg", user_id: str = "u1", session_id: str = "tg:web:u1", args: list[str] | None = None
) -> CommandContext:
    event = IncomingMessage(channel=channel, user_id=user_id, session_id=session_id, text="/cmd")
    return CommandContext(event=event, user={}, args=args or [])


def _sent(gw: _FakeGateway) -> tuple[str, str, str]:
    call = gw._send.await_args
    return call.args[0], call.args[1], call.args[2]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------


async def test_help_lists_commands() -> None:
    gw = _FakeGateway()
    assert await HelpCommand(gw).execute(_ctx()) is True
    _, _, msg = _sent(gw)
    assert "Commands:" in msg
    assert "/status" in msg and "/voice tts" in msg and "/mcp" in msg


# ---------------------------------------------------------------------------
# reset / new_session — session-id resolution has two forms
# ---------------------------------------------------------------------------


async def test_reset_uses_existing_session_id() -> None:
    gw = _FakeGateway()
    assert await ResetCommand(gw).execute(_ctx(session_id="tg:web:u1")) is True
    gw.db.delete_session.assert_awaited_once_with("tg:web:u1")
    assert _sent(gw) == ("tg", "tg:web:u1", "Session reset.")


async def test_reset_falls_back_to_default_session_id() -> None:
    gw = _FakeGateway()
    await ResetCommand(gw).execute(_ctx(channel="dc", user_id="u9", session_id=""))
    gw.db.delete_session.assert_awaited_once_with("dc:u9:default")
    assert _sent(gw) == ("dc", "dc:u9:default", "Session reset.")


async def test_new_session_uses_existing_session_id() -> None:
    gw = _FakeGateway()
    assert await NewSessionCommand(gw).execute(_ctx(session_id="tg:web:u1")) is True
    gw.db.delete_session.assert_awaited_once_with("tg:web:u1")
    assert _sent(gw) == ("tg", "tg:web:u1", "Starting fresh conversation.")


async def test_new_session_falls_back_to_default_session_id() -> None:
    gw = _FakeGateway()
    await NewSessionCommand(gw).execute(_ctx(channel="wa", user_id="u5", session_id=""))
    gw.db.delete_session.assert_awaited_once_with("wa:u5:default")
    assert _sent(gw) == ("wa", "wa:u5:default", "Starting fresh conversation.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


async def test_status_reports_channels_agents_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = _FakeGateway()
    gw.channels.list_ids = AsyncMock(return_value=["telegram", "webchat"])
    gw.registry = SimpleNamespace(list_agents=lambda: ["a", "b", "c"])
    monkeypatch.setattr(skills_registry, "list_names", lambda: ["s1", "s2"])
    assert await StatusCommand(gw).execute(_ctx()) is True
    _, _, msg = _sent(gw)
    assert "Raven AI is running." in msg
    assert "Channels: telegram, webchat" in msg
    assert "Agents: 3" in msg
    assert "Skills: 2" in msg


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


async def test_mcp_no_servers() -> None:
    gw = _FakeGateway()
    gw.mcp = SimpleNamespace(connected_count=0, list_servers_info=lambda: [])
    assert await MCPCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "No MCP servers connected."


async def test_mcp_lists_servers() -> None:
    gw = _FakeGateway()
    gw.mcp = SimpleNamespace(
        connected_count=2,
        list_servers_info=lambda: [
            {"name": "filesystem", "tools": 5},
            {"name": "github", "tools": 12},
        ],
    )
    assert await MCPCommand(gw).execute(_ctx()) is True
    msg = _sent(gw)[2]
    assert msg.startswith("🌐 MCP servers (2 connected):")
    assert "  filesystem: 5 tools" in msg
    assert "  github: 12 tools" in msg


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------


async def test_skills_registry_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skills_registry, "list_names", lambda: ["alpha", "beta"])
    gw = _FakeGateway()
    assert await SkillsCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Skills: alpha, beta"


async def test_skills_merges_artifact_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skills_registry, "list_names", lambda: ["core"])
    mgr = SimpleNamespace(skills_index=lambda: [SimpleNamespace(name="artifact-skill")])
    monkeypatch.setattr("raven.core.artifacts.get_artifact_manager", lambda cwd: mgr)
    gw = _FakeGateway()
    gw._artifact_root = "/tmp/root"
    assert await SkillsCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Skills: artifact-skill, core"


async def test_skills_artifact_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skills_registry, "list_names", lambda: ["only"])

    def _boom(cwd: object) -> object:
        raise RuntimeError("artifact manager down")

    monkeypatch.setattr("raven.core.artifacts.get_artifact_manager", _boom)
    gw = _FakeGateway()
    gw._artifact_root = "/tmp/root"
    assert await SkillsCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Skills: only"


async def test_skills_none_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skills_registry, "list_names", lambda: [])
    gw = _FakeGateway()
    assert await SkillsCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "No skills loaded."


# ---------------------------------------------------------------------------
# CommandRegistry
# ---------------------------------------------------------------------------


class _EchoHandler(CommandHandler):
    name = "echo"
    description = "echo back"

    def __init__(self) -> None:
        super().__init__(gateway=object())
        self.ran = False

    async def execute(self, ctx: CommandContext) -> bool:
        self.ran = True
        return True


async def test_registry_get_and_execute() -> None:
    reg = CommandRegistry()
    handler = _EchoHandler()
    reg.register(handler)
    assert reg.get("echo") is handler
    assert reg.get("missing") is None
    assert list(reg.list_commands()) == [handler]
    assert await reg.execute("echo", _ctx()) is True
    assert handler.ran is True
    assert await reg.execute("missing", _ctx()) is False


# ---------------------------------------------------------------------------
# settings: five pref toggles share one valid/invalid shape, plus restart
# ---------------------------------------------------------------------------


async def test_think_valid() -> None:
    gw = _FakeGateway()
    assert await ThinkCommand(gw).execute(_ctx(args=["low"])) is True
    gw.set_pref.assert_called_once_with("tg", "u1", "think_level", "low")
    assert _sent(gw)[2] == "Thinking level set to: low."


async def test_think_invalid_shows_current() -> None:
    gw = _FakeGateway()
    gw.get_pref = MagicMock(return_value="medium")
    assert await ThinkCommand(gw).execute(_ctx(args=["bogus"])) is True
    gw.set_pref.assert_not_called()
    assert _sent(gw)[2] == "Thinking level: medium.\nUsage: /think <low|medium|high>"


async def test_verbose_valid_and_invalid() -> None:
    gw = _FakeGateway()
    await VerboseCommand(gw).execute(_ctx(args=["on"]))
    gw.set_pref.assert_called_once_with("tg", "u1", "verbose", "on")
    assert _sent(gw)[2] == "Verbose mode: on."
    gw2 = _FakeGateway()
    await VerboseCommand(gw2).execute(_ctx())
    assert "Usage: /verbose <on|off>" in _sent(gw2)[2]


async def test_trace_valid_and_invalid() -> None:
    gw = _FakeGateway()
    await TraceCommand(gw).execute(_ctx(args=["off"]))
    gw.set_pref.assert_called_once_with("tg", "u1", "trace", "off")
    assert _sent(gw)[2] == "Trace mode: off."
    gw2 = _FakeGateway()
    await TraceCommand(gw2).execute(_ctx())
    assert "Usage: /trace <on|off>" in _sent(gw2)[2]


async def test_usage_valid_and_invalid() -> None:
    gw = _FakeGateway()
    await UsageCommand(gw).execute(_ctx(args=["tokens"]))
    gw.set_pref.assert_called_once_with("tg", "u1", "usage_mode", "tokens")
    assert _sent(gw)[2] == "Usage mode: tokens."
    gw2 = _FakeGateway()
    await UsageCommand(gw2).execute(_ctx())
    assert "Usage: /usage <off|tokens|full>" in _sent(gw2)[2]


async def test_activation_valid_and_invalid() -> None:
    gw = _FakeGateway()
    await ActivationCommand(gw).execute(_ctx(args=["always"]))
    gw.set_pref.assert_called_once_with("tg", "u1", "activation_mode", "always")
    assert _sent(gw)[2] == "Activation mode: always."
    gw2 = _FakeGateway()
    await ActivationCommand(gw2).execute(_ctx())
    assert "Usage: /activation <mention|always>" in _sent(gw2)[2]


async def test_restart_existing_and_default_session() -> None:
    gw = _FakeGateway()
    assert await RestartCommand(gw).execute(_ctx(session_id="tg:web:u1")) is True
    gw.db.delete_session.assert_awaited_once_with("tg:web:u1")
    assert _sent(gw) == ("tg", "tg:web:u1", "Session restarted.")
    gw2 = _FakeGateway()
    await RestartCommand(gw2).execute(_ctx(channel="ig", user_id="u7", session_id=""))
    gw2.db.delete_session.assert_awaited_once_with("ig:u7:default")


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


class _Agent:
    def __init__(self, tokens: list[str] | None = None, exc: Exception | None = None) -> None:
        self._tokens = tokens or []
        self._exc = exc

    async def simple_complete(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if self._exc is not None:
            raise self._exc
        for t in self._tokens:
            yield t


def _compact_gw(*, msgs: list[Any], agent: _Agent) -> _FakeGateway:
    gw = _FakeGateway()
    gw.db = SimpleNamespace(
        get_or_create_session=AsyncMock(return_value=SimpleNamespace(id="sid-1")),
        get_session_messages=AsyncMock(return_value=msgs),
        replace_session_messages=AsyncMock(),
    )
    gw.registry = SimpleNamespace(create_agent=lambda session: agent)
    return gw


async def test_compact_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.compact.get_policy_for_channel", lambda ch: object())
    monkeypatch.setattr(
        "raven.core.gateway.commands.compact.check_tool_allowed", lambda policy, action, ch: (False, "locked")
    )
    gw = _FakeGateway()
    assert await CompactCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Access denied: locked"


async def test_compact_no_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.compact.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    gw = _compact_gw(msgs=[], agent=_Agent(["x"]))
    assert await CompactCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "No messages to compact."


async def test_compact_summarizer_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.compact.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    msgs = [SimpleNamespace(role="user", content="hello " * 50)]
    gw = _compact_gw(msgs=msgs, agent=_Agent(exc=RuntimeError("llm down")))
    assert await CompactCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Compact failed — conversation left unchanged."


async def test_compact_empty_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.compact.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    gw = _compact_gw(msgs=[SimpleNamespace(role="user", content="hi")], agent=_Agent(["   "]))
    assert await CompactCommand(gw).execute(_ctx()) is True
    assert "empty summary" in _sent(gw)[2]


async def test_compact_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.compact.get_policy_for_channel", lambda ch: object())
    monkeypatch.setattr(
        "raven.core.gateway.commands.compact.check_tool_allowed", lambda policy, action, ch: (True, "")
    )
    msgs = [SimpleNamespace(role="user", content="a" * 300), SimpleNamespace(role="assistant", content="b")]
    gw = _compact_gw(msgs=msgs, agent=_Agent(["All ", "good "]))
    assert await CompactCommand(gw).execute(_ctx()) is True
    gw.db.replace_session_messages.assert_awaited_once_with(
        "sid-1", [{"role": "system", "content": "[Session compacted: All good ]"}]
    )
    assert _sent(gw)[2] == "Session compacted.\nSummary: All good "


# ---------------------------------------------------------------------------
# agent / agent_status
# ---------------------------------------------------------------------------

_VALID_PROFILE = next(iter(PROFILES))


def test_agent_name_and_description() -> None:
    cmd = AgentCommand(_FakeGateway())
    assert cmd.name == "agent"
    assert "/agent <profile>" in cmd.description
    assert _VALID_PROFILE in cmd.description


async def test_agent_no_args_lists_profiles() -> None:
    gw = _FakeGateway()
    assert await AgentCommand(gw).execute(_ctx()) is True
    msg = _sent(gw)[2]
    assert "Available agent profiles:" in msg
    assert f"/agent {_VALID_PROFILE}" in msg
    assert "Usage: /agent <profile>" in msg


async def test_agent_unknown_profile() -> None:
    gw = _FakeGateway()
    assert await AgentCommand(gw).execute(_ctx(args=["definitely_not_real"])) is True
    assert _sent(gw)[2].startswith("Unknown profile: definitely_not_real.")


async def test_agent_valid_profile_switches() -> None:
    gw = _FakeGateway()
    ctx = _ctx(args=[_VALID_PROFILE.upper()])
    assert await AgentCommand(gw).execute(ctx) is True
    assert ctx.user["agent_profile"] == _VALID_PROFILE
    assert _sent(gw)[2] == f"Switched to agent profile: {PROFILES[_VALID_PROFILE].display_name}"


def test_agent_status_name_and_description() -> None:
    cmd = AgentStatusCommand(_FakeGateway())
    assert cmd.name == "agent_status"
    assert cmd.description == "Show current agent profile and status"


async def test_agent_status_defaults_to_auto() -> None:
    gw = _FakeGateway()
    assert await AgentStatusCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2].startswith("Current agent mode: auto")


async def test_agent_status_shows_current() -> None:
    gw = _FakeGateway()
    ctx = _ctx()
    ctx.user["agent_profile"] = "coder"
    assert await AgentStatusCommand(gw).execute(ctx) is True
    assert _sent(gw)[2].startswith("Current agent mode: coder")


# ---------------------------------------------------------------------------
# task
# ---------------------------------------------------------------------------


def _task_gw(*, perm: bool = True) -> _FakeGateway:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(return_value=perm)
    return gw


async def test_task_access_denied_by_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.task.get_policy_for_channel", lambda ch: object())
    monkeypatch.setattr("raven.core.gateway.commands.task.check_tool_allowed", lambda p, a, ch: (False, "no gateway"))
    gw = _task_gw()
    assert await TaskCommand(gw).execute(_ctx(args=["x"])) is True
    assert _sent(gw)[2] == "Access denied: no gateway"


async def test_task_insufficient_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.task.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    gw = _task_gw(perm=False)
    assert await TaskCommand(gw).execute(_ctx(args=["x"])) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_task_empty_goal_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.task.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    gw = _task_gw()
    assert await TaskCommand(gw).execute(_ctx(args=[])) is True
    assert _sent(gw)[2] == "Usage: /task <goal description>"


async def test_task_runs_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY

    monkeypatch.setattr("raven.core.gateway.commands.task.get_policy_for_channel", lambda ch: MAIN_SESSION_POLICY)
    gw = _task_gw()
    ctx = _ctx(args=["build", "a", "report"])
    assert await TaskCommand(gw).execute(ctx) is True
    gw._check_permission.assert_called_once_with(ctx.user, Permission.TASK_RUN)
    assert _sent(gw)[2] == "Planning task: build a report..."
    gw.tasks.create_and_run.assert_called_once_with(
        goal="build a report", user_id="u1", channel="tg", session_id="tg:web:u1"
    )
    gw._bg_task.assert_awaited_once_with("coro")
