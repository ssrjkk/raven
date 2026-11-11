"""The `raven code` REPL session commands.

`/session <id>` used to call `run_coroutine_threadsafe(...).result()` from inside the running loop,
which blocks the loop that would have to execute the coroutine: the REPL hung forever. It also
printed "Switched to session" without adopting anything, and the id it printed was an 8-character
prefix the lookup could not resolve. Each of those is a separate assertion here.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import io
import re
import textwrap
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from raven.cli import coding
from ravencode.runtime.agent_core import AgentConfig
from ravencode.runtime.context import Conversation
from ravencode.runtime.multisession import SessionManager


def _fake_agent(result: str = "done") -> Any:
    agent = SimpleNamespace(
        name="raven",
        config=AgentConfig(),
        conversation=Conversation(),
        aborted=False,
    )
    agent.run = AsyncMock(return_value=result)
    agent.abort = lambda: None
    return agent


@pytest.fixture
def mgr() -> Iterator[SessionManager]:
    manager = SessionManager()
    with patch.object(coding, "get_session_manager", return_value=manager):
        yield manager


@pytest.fixture
def out() -> Iterator[io.StringIO]:
    buf = io.StringIO()
    with patch.object(coding, "console", Console(file=buf, width=200, no_color=True)):
        yield buf


def _current_agent() -> Any:
    agent = _fake_agent()
    agent.conversation = Conversation(system_prompt="the REPL conversation")
    return agent


class TestSwitchSession:
    async def test_adopts_the_session_conversation(self, mgr: SessionManager, out: io.StringIO) -> None:
        fake = _fake_agent()
        fake.conversation.add_user_message("work done in the session")
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            session = await mgr.create(name="work")
        current = _current_agent()

        await coding._switch_session(session.id, current)

        assert current.conversation is fake.conversation
        assert "Switched to session" in out.getvalue()

    async def test_resolves_the_prefix_the_table_displays(self, mgr: SessionManager, out: io.StringIO) -> None:
        fake = _fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            session = await mgr.create(name="work")
        current = _current_agent()

        coding._show_multisessions()
        displayed = session.id[:8]
        assert displayed in out.getvalue()

        await coding._switch_session(displayed, current)
        assert current.conversation is fake.conversation

    async def test_returns_inside_a_running_loop(self, mgr: SessionManager, out: io.StringIO) -> None:
        """The deadlock regression: the old implementation never returned while the loop ran."""
        fake = _fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            session = await mgr.create(name="work")

        await asyncio.wait_for(coding._switch_session(session.id, _current_agent()), timeout=5)

    async def test_unknown_id_changes_nothing_and_says_so(self, mgr: SessionManager, out: io.StringIO) -> None:
        current = _current_agent()
        before = current.conversation

        await coding._switch_session("ffffffff", current)

        assert current.conversation is before
        assert "No session matches: ffffffff" in out.getvalue()
        assert "Switched" not in out.getvalue()

    async def test_ambiguous_prefix_is_refused(self, mgr: SessionManager, out: io.StringIO) -> None:
        ids = [SimpleNamespace(hex="abcd11110000"), SimpleNamespace(hex="abcd22220000")]
        with (
            patch("ravencode.runtime.multisession.ReActAgent", side_effect=lambda **kw: _fake_agent()),
            patch("ravencode.runtime.multisession.uuid.uuid4", side_effect=ids),
        ):
            await mgr.create(name="one")
            await mgr.create(name="two")
        current = _current_agent()
        before = current.conversation

        await coding._switch_session("abcd", current)

        assert current.conversation is before
        assert "Ambiguous id abcd" in out.getvalue()


class TestStartNamedSession:
    async def test_runs_the_task_and_keeps_the_session_switchable(self, mgr: SessionManager, out: io.StringIO) -> None:
        fake = _fake_agent(result="the answer")
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            await coding._start_named_session("work", "add a flag", _current_agent())

        assert [s.name for s in mgr.sessions] == ["work"]
        fake.run.assert_awaited_once_with("add a flag")
        text = out.getvalue()
        assert "the answer" in text

        session = await mgr.get(mgr.sessions[0].id)
        assert session is not None
        current = _current_agent()
        await coding._switch_session(session.id[:8], current)
        assert current.conversation is fake.conversation

    async def test_inherits_the_repl_safety_settings(self, mgr: SessionManager) -> None:
        current = _current_agent()
        current.config.confirm_dangerous = True
        current.config.max_steps = 7
        with patch("ravencode.runtime.multisession.ReActAgent") as ctor:
            ctor.return_value = _fake_agent()
            await coding._start_named_session("work", "task", current)

        config = ctor.call_args.kwargs["config"]
        assert config.confirm_dangerous is True
        assert config.max_steps == 7


class TestInteractiveDispatch:
    async def _run_repl(self, lines: list[str], agent: Any) -> None:
        pending = list(lines)

        def read() -> str:
            if not pending:
                raise EOFError
            return pending.pop(0)

        with patch.object(coding, "_read_input", read):
            await asyncio.wait_for(coding._run_interactive(agent, None), timeout=10)

    async def test_session_command_starts_then_switches(self, mgr: SessionManager, out: io.StringIO) -> None:
        fake = _fake_agent()
        fake.conversation.add_user_message("from the named session")
        current = _current_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            await self._run_repl(["/session work add a flag", "/multisession", "/exit"], current)

        assert [s.name for s in mgr.sessions] == ["work"]
        assert "work" in out.getvalue()

        await self._run_repl([f"/session {mgr.sessions[0].id[:8]}", "/exit"], current)
        assert current.conversation is fake.conversation

    async def test_bare_session_command_prints_usage(self, mgr: SessionManager, out: io.StringIO) -> None:
        await self._run_repl(["/session", "/exit"], _current_agent())
        assert "Usage: /session <id> | /session <name> <task>" in out.getvalue()

    async def test_task_with_spaces_reaches_the_session(self, mgr: SessionManager) -> None:
        fake = _fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            await self._run_repl(['/session work "add a flag" and a test', "/exit"], _current_agent())
        fake.run.assert_awaited_once_with("add a flag and a test")


class TestCommandSurface:
    def test_every_handled_command_is_documented_and_vice_versa(self, out: io.StringIO) -> None:
        coding._print_welcome()
        documented = set(re.findall(r"/[a-z]+", out.getvalue()))
        handled = _handled_commands()
        assert handled == documented, (
            f"undocumented: {sorted(handled - documented)}, absent: {sorted(documented - handled)}"
        )


def _handled_commands() -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(coding._run_interactive)))
    found: set[str] = set()

    def collect(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("/") and len(node.value) > 1:
                found.add(node.value)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                collect(elt)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comp in node.comparators:
                collect(comp)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith":
            for arg in node.args:
                collect(arg)
    return found
