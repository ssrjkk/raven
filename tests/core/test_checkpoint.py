from __future__ import annotations

import json

import pytest

from raven.core.checkpoint import CheckpointManager
from raven.core.db import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.connect()
    yield d
    await d.disconnect()


@pytest.fixture
async def mgr(db):
    return CheckpointManager(db)


@pytest.mark.asyncio
async def test_save_returns_id(mgr):
    cid = await mgr.save("session-1", [{"role": "user", "content": "hi"}], {"step": 1})
    assert isinstance(cid, str)
    assert len(cid) > 0


@pytest.mark.asyncio
async def test_save_and_load(mgr):
    cid = await mgr.save("session-1", [{"role": "user", "content": "hello"}], {"step": 2})
    cp = await mgr.load(cid)
    assert cp is not None
    assert cp.session_id == "session-1"
    assert cp.messages == [{"role": "user", "content": "hello"}]
    assert cp.agent_state == {"step": 2}


@pytest.mark.asyncio
async def test_load_nonexistent_returns_none(mgr):
    cp = await mgr.load("nonexistent-id")
    assert cp is None


@pytest.mark.asyncio
async def test_list_checkpoints(mgr):
    await mgr.save("session-1", [{"role": "user", "content": "a"}], {})
    await mgr.save("session-1", [{"role": "user", "content": "b"}], {})
    cps = await mgr.list_checkpoints("session-1")
    assert len(cps) == 2


@pytest.mark.asyncio
async def test_delete(mgr):
    cid = await mgr.save("session-1", [{"role": "user", "content": "x"}], {})
    await mgr.delete(cid)
    cp = await mgr.load(cid)
    assert cp is None
