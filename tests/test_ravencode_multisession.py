from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ravencode.runtime.agent_core import AgentConfig
from ravencode.runtime.multisession import ManagedSession, SessionManager, get_session_manager


def make_fake_agent(name: str = "raven", result: str = "done", exc: BaseException | None = None) -> Any:
    agent = SimpleNamespace(name=name, config=AgentConfig(), aborted=False)

    async def run(user_input: str) -> str:
        agent.last_input = user_input
        if exc is not None:
            raise exc
        return result

    def abort() -> None:
        agent.aborted = True

    agent.run = run
    agent.abort = abort
    return agent


class TestManagedSession:
    async def test_info(self) -> None:
        session = ManagedSession("sid1", "My Session", make_fake_agent())
        info = session.info
        assert info.id == "sid1"
        assert info.name == "My Session"
        assert info.status == "idle"
        assert info.agent_type == "raven"
        assert info.message_count == 0
        assert info.step_count == 0

    async def test_run_success(self) -> None:
        session = ManagedSession("sid1", "s", make_fake_agent())
        result = await session.run("hello")
        assert result == "done"
        assert session.status == "idle"
        assert session.message_count == 1

    async def test_run_counts_steps(self) -> None:
        agent = make_fake_agent()
        session = ManagedSession("sid1", "s", agent)
        await session.run("hello")
        assert agent.config.on_step is not None
        await agent.config.on_step("msg", 3)
        assert session.step_count == 3

    async def test_run_cancelled(self) -> None:
        agent = make_fake_agent(exc=asyncio.CancelledError())
        session = ManagedSession("sid1", "s", agent)
        result = await session.run("hello")
        assert result == "[cancelled]"
        assert session.status == "idle"

    async def test_run_error(self) -> None:
        agent = make_fake_agent(exc=RuntimeError("boom"))
        session = ManagedSession("sid1", "s", agent)
        result = await session.run("hello")
        assert result == "[error: boom]"
        assert session.status == "idle"

    async def test_run_existing_on_step(self) -> None:
        agent = make_fake_agent()
        calls: list[tuple[str, int]] = []

        async def existing(msg: str, step: int) -> None:
            calls.append((msg, step))

        agent.config.on_step = existing
        session = ManagedSession("sid1", "s", agent)
        await session.run("hello")
        assert session.step_count == 0
        assert agent.config.on_step is not None
        await agent.config.on_step("m", 5)
        assert session.step_count == 5
        assert calls == [("m", 5)]

    def test_abort(self) -> None:
        agent = make_fake_agent()
        session = ManagedSession("sid1", "s", agent)
        session.abort()
        assert agent.aborted is True


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_create(self) -> None:
        fake = make_fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            mgr = SessionManager()
            session = await mgr.create(name="test", agent_type="custom")
        assert session.name == "test"
        assert session.agent is fake
        assert session.id

    @pytest.mark.asyncio
    async def test_create_default_name(self) -> None:
        fake = make_fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            mgr = SessionManager()
            session = await mgr.create()
        assert session.name.startswith("session-")

    @pytest.mark.asyncio
    async def test_get_and_sessions(self) -> None:
        fake = make_fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            mgr = SessionManager()
            session = await mgr.create(name="a")
            assert await mgr.get(session.id) is session
            assert len(mgr.sessions) == 1
            assert mgr.sessions[0].name == "a"

    @pytest.mark.asyncio
    async def test_get_missing(self) -> None:
        mgr = SessionManager()
        assert await mgr.get("nope") is None

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        fake = make_fake_agent()
        with patch("ravencode.runtime.multisession.ReActAgent", return_value=fake):
            mgr = SessionManager()
            session = await mgr.create(name="a")
            assert await mgr.remove(session.id) is True
            assert fake.aborted is True
            assert await mgr.get(session.id) is None

    @pytest.mark.asyncio
    async def test_remove_missing(self) -> None:
        mgr = SessionManager()
        assert await mgr.remove("nope") is False

    @pytest.mark.asyncio
    async def test_abort_all_and_cleanup(self) -> None:
        fakes = [make_fake_agent(), make_fake_agent()]
        with patch("ravencode.runtime.multisession.ReActAgent", side_effect=fakes):
            mgr = SessionManager()
            await mgr.create(name="a")
            await mgr.create(name="b")
            await mgr.abort_all()
            assert all(f.aborted for f in fakes)
            await mgr.cleanup()
            assert mgr.sessions == []

    async def test_get_session_manager_singleton(self) -> None:
        mgr = get_session_manager()
        assert get_session_manager() is mgr


class TestManagedSessionTask:
    @pytest.mark.asyncio
    async def test_run_sets_task(self) -> None:
        agent = make_fake_agent()
        session = ManagedSession("sid1", "s", agent)
        await session.run("hello")
        assert session._task is not None
