from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.runtime.session as session_mod
from ravencode.runtime.agent_core import ReActAgent, _last_agent_var
from ravencode.runtime.session import SessionStore, get_session_store, session_load, session_save, validate_session_id


def _fake_agent() -> Any:
    return MagicMock(
        dump_state=MagicMock(return_value={"config": {"max_steps": 5}, "name": "raven", "conversation": []}),
        conversation=MagicMock(message_count=3),
    )


@pytest.fixture(autouse=True)
def reset() -> Generator[None, None, None]:
    session_mod._session_store = None
    token = _last_agent_var.set(None)
    yield
    session_mod._session_store = None
    _last_agent_var.reset(token)


class TestSessionStoreInit:
    def test_creates_dir(self, tmp_path) -> None:
        target = tmp_path / "sub" / "sessions"
        store = SessionStore(str(target))
        assert target.is_dir()


class TestSaveLoadDelete:
    async def test_save_creates_json(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        sid = await store.save(_fake_agent(), summary="sum")
        f = tmp_path / f"{sid}.json"
        assert f.is_file()
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["summary"] == "sum"
        assert data["steps"] == 3
        assert "created" in data and "updated" in data

    async def test_load_missing(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        assert await store.load("nope") is None

    async def test_load_corrupt_json(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        assert await store.load("bad") is None

    async def test_load_valid(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        data = {
            "config": {"max_steps": 5},
            "conversation": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            "name": "custom",
        }
        (tmp_path / "sid1.json").write_text(json.dumps(data), encoding="utf-8")
        agent = await store.load("sid1")
        assert agent is not None
        assert agent.name == "custom"
        assert agent.config.max_steps == 5
        assert agent.conversation.messages[-1] == {"role": "user", "content": "hi"}
        # loading a session must make it the live agent, or /ask starts blank
        assert ReActAgent.last_agent() is agent

    async def test_delete_exists(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        (tmp_path / "sid1.json").write_text("{}", encoding="utf-8")
        assert await store.delete("sid1") is True
        assert not (tmp_path / "sid1.json").exists()

    async def test_delete_missing(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        assert await store.delete("nope") is False


class TestList:
    async def test_list_sorted_by_updated_desc(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        (tmp_path / "a.json").write_text(
            json.dumps({"created": 1, "updated": 1, "summary": "A", "steps": 2}), encoding="utf-8"
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"created": 2, "updated": 3, "summary": "B", "steps": 5}), encoding="utf-8"
        )
        sessions = store.list()
        assert [s["id"] for s in sessions] == ["b", "a"]
        assert sessions[0]["summary"] == "B"
        assert sessions[0]["steps"] == 5

    async def test_list_skips_corrupt(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        (tmp_path / "a.json").write_text("garbage", encoding="utf-8")
        assert store.list() == []

    async def test_list_empty(self, tmp_path) -> None:
        assert SessionStore(str(tmp_path)).list() == []


class TestGlobals:
    def test_get_session_store_singleton(self, tmp_path) -> None:
        session_mod._session_store = None
        store = get_session_store(str(tmp_path))
        assert get_session_store(str(tmp_path)) is store

    async def test_session_save_delegates(self, tmp_path, monkeypatch) -> None:
        fake_store = MagicMock()
        fake_store.save = AsyncMock(return_value="sid_abc")
        monkeypatch.setattr(session_mod, "get_session_store", lambda: fake_store)
        assert await session_save(_fake_agent(), "s") == "sid_abc"

    async def test_session_load_delegates(self, tmp_path, monkeypatch) -> None:
        fake_store = MagicMock()
        fake_store.load = AsyncMock(return_value=None)
        monkeypatch.setattr(session_mod, "get_session_store", lambda: fake_store)
        assert await session_load("x") is None


class TestValidateSessionId:
    @pytest.mark.parametrize(
        "session_id",
        ["abc123", "session_deadbeef12", "A-b_9", "x" * 128],
    )
    def test_accepts_safe_ids(self, session_id: str) -> None:
        assert validate_session_id(session_id) == session_id

    @pytest.mark.parametrize(
        "session_id",
        ["", ".", "..", "../escape", "a/b", "a\\b", "/abs/path", "x" * 129, "has space", "nul\x00", "séssion"],
    )
    def test_rejects_unsafe_ids(self, session_id: str) -> None:
        with pytest.raises(ValueError, match="Invalid session id"):
            validate_session_id(session_id)

    def test_store_path_uses_the_validator(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path))
        with pytest.raises(ValueError):
            store._path("../../outside")
