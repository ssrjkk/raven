from __future__ import annotations

from pathlib import Path

import pytest

from raven.gateway.daemon import FlowSession, RavenFlowDaemon
from raven.gateway.session_store import SessionStore


def make_session(session_id: str = "abc123", message_count: int = 3) -> FlowSession:
    return FlowSession(id=session_id, channel="test", created_at="2026-01-01T00:00:00+00:00", message_count=message_count)


class TestSessionStoreRoundTrip:
    def test_save_and_load(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session())
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].id == "abc123"
        assert loaded[0].channel == "test"
        assert loaded[0].message_count == 3
        assert loaded[0].agent is None

    def test_load_empty(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        assert store.load_all() == []
        assert store.count() == 0

    def test_remove(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session())
        store.remove("abc123")
        assert store.count() == 0

    def test_remove_missing_is_noop(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.remove("nope")
        assert store.count() == 0

    def test_overwrite_same_id(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session(message_count=1))
        store.save(make_session(message_count=7))
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].message_count == 7

    def test_corrupt_file_skipped(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session())
        (store.directory / "bad.json").write_text("{not json", encoding="utf-8")
        assert len(store.load_all()) == 1

    def test_prune_removes_old_files(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session("old"))
        old_file = store.directory / "old.json"
        store.save(make_session("new"))
        new_file = store.directory / "new.json"
        old_ts = new_file.stat().st_mtime - 600
        import os

        os.utime(old_file, (old_ts, old_ts))
        assert store.prune(max_age_seconds=300) == 1
        assert store.count() == 1


class TestFlowSessionDict:
    def test_to_dict_excludes_agent_and_task(self):
        d = make_session().to_dict()
        assert d == {
            "id": "abc123",
            "channel": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "message_count": 3,
            "status": "idle",
        }
        assert "agent" not in d
        assert "_task" not in d

    def test_from_dict_roundtrip(self):
        session = FlowSession.from_dict(make_session().to_dict())
        assert session is not None
        assert session.id == "abc123"
        assert session.message_count == 3
        assert session.agent is None

    def test_from_dict_invalid(self):
        assert FlowSession.from_dict({}) is None
        assert FlowSession.from_dict({"id": ""}) is None

    def test_from_dict_negative_message_count_clamped(self):
        session = FlowSession.from_dict({"id": "x", "message_count": -5})
        assert session is not None
        assert session.message_count == 0


@pytest.fixture
def daemon(tmp_path: Path):
    return RavenFlowDaemon(port=0, data_dir=tmp_path)


@pytest.mark.asyncio
class TestDaemonFlush:
    async def test_mark_dirty_and_flush(self, daemon, tmp_path: Path):
        session = make_session()
        daemon.sessions[session.id] = session
        daemon._mark_dirty(session.id)
        assert daemon._dirty == {"abc123"}
        await daemon._flush_dirty()
        assert daemon._dirty == set()
        assert daemon._store.count() == 1

    async def test_batched_flush_writes_multiple(self, daemon):
        for sid in ("a", "b", "c"):
            daemon.sessions[sid] = make_session(sid)
            daemon._mark_dirty(sid)
        await daemon._flush_dirty()
        assert daemon._store.count() == 3

    async def test_flush_drops_missing_session(self, daemon):
        daemon._mark_dirty("ghost")
        await daemon._flush_dirty()
        assert daemon._store.count() == 0
        assert daemon._dirty == set()

    async def test_flush_persists_message_count(self, daemon):
        session = make_session(message_count=42)
        daemon.sessions[session.id] = session
        daemon._mark_dirty(session.id)
        await daemon._flush_dirty()
        loaded = daemon._store.load_all()
        assert loaded[0].message_count == 42

    async def test_stop_flushes_dirty(self, daemon, tmp_path: Path):
        session = make_session()
        daemon.sessions[session.id] = session
        daemon._mark_dirty(session.id)
        await daemon.stop()
        assert daemon._store.count() == 1

    async def test_flush_loop_tick(self, daemon):
        session = make_session()
        daemon.sessions[session.id] = session
        daemon._mark_dirty(session.id)
        daemon._flush_task = None
        await daemon._flush_dirty()
        assert daemon._store.count() == 1


class TestDaemonRestore:
    def test_load_persisted_sessions_marks_resumed(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session(message_count=5))
        daemon = RavenFlowDaemon(port=0, data_dir=tmp_path)
        daemon._load_persisted_sessions()
        assert daemon.sessions["abc123"].status == "resumed"
        assert daemon.sessions["abc123"].message_count == 5
        assert daemon.sessions["abc123"].agent is None

    def test_restore_skips_duplicates(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session(message_count=1))
        daemon = RavenFlowDaemon(port=0, data_dir=tmp_path)
        daemon.sessions["abc123"] = make_session(message_count=9)
        daemon._load_persisted_sessions()
        assert daemon.sessions["abc123"].message_count == 9

    def test_get_or_create_builds_agent_for_resumed(self, tmp_path: Path):
        store = SessionStore(tmp_path)
        store.save(make_session(message_count=5))
        daemon = RavenFlowDaemon(port=0, data_dir=tmp_path)
        daemon._load_persisted_sessions()
        import asyncio

        session = asyncio.run(daemon._get_or_create_session("abc123", "test", "build"))
        assert session.agent is not None
        assert session.message_count == 5
