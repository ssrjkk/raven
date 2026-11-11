"""Seven statements in this project interpolate SQL with an f-string and carry a `# nosec B608`.

The annotation is a claim, not a fix, so the claim is what these tests measure: the only text that
reaches the interpolated slot is a clause spelled out in `_ALLOWED_CLAUSES` / `_ALLOWED_WHERE` or a run
of `?` markers, and everything the caller supplied travels as a bound parameter. The two properties
that make that true are asserted directly — a hostile value never appears in the statement string, and
a clause the allowlist does not spell is refused before the statement is built. If either stops
holding, the annotation is lying and these tests are the gate that says so.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from raven.core.coder.models import CodingSession
from raven.core.coder.session import CodingSessionManager
from raven.core.task_engine.models import Task, TaskStatus
from raven.core.task_engine.store import TaskStore

ROOT = Path(__file__).resolve().parent.parent
HOSTILE = "bob' OR '1'='1"


def _statement_spy(store: Any, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Record every `(sql, params)` the store hands to the driver, then run the real query."""
    seen: list[tuple[str, Any]] = []
    real_fetchall = store._fetchall
    real_fetchone = store._fetchone

    async def _fetchall(sql: str, params: Any = ()) -> list[Any]:
        seen.append((sql, params))
        return list(await real_fetchall(sql, params))

    async def _fetchone(sql: str, params: Any = ()) -> Any:
        seen.append((sql, params))
        return await real_fetchone(sql, params)

    monkeypatch.setattr(store, "_fetchall", _fetchall)
    monkeypatch.setattr(store, "_fetchone", _fetchone)
    return seen


@pytest.fixture
async def task_store(tmp_path: Path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    yield store
    await store.close()


@pytest.fixture
async def session_store(tmp_path: Path):
    manager = CodingSessionManager(str(tmp_path / "sessions.db"))
    yield manager
    await manager.close()


class TestTaskStoreInterpolation:
    async def test_the_filter_travels_as_a_parameter_never_as_text(
        self, task_store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _statement_spy(task_store, monkeypatch)
        await task_store.list_tasks(user_id=HOSTILE, status="completed")
        await task_store.count_tasks(user_id=HOSTILE, status="completed")
        assert seen, "the guard below is only a guard if the query is really built"
        for sql, params in seen:
            assert HOSTILE not in sql, sql
            assert "user_id = ?" in sql and "status = ?" in sql, sql
            assert params[0] == HOSTILE, params

    async def test_a_user_id_that_reads_like_sql_returns_nothing_it_should_not(self, task_store: TaskStore) -> None:
        await task_store.save_task(Task(user_id="alice", goal="keep"))
        await task_store.save_task(Task(user_id="bob", goal="keep"))
        assert len(await task_store.list_tasks()) == 2
        assert await task_store.list_tasks(user_id=HOSTILE) == []
        assert await task_store.count_tasks(user_id=HOSTILE) == 0
        assert len(await task_store.list_tasks(user_id="bob")) == 1

    async def test_a_clause_the_allowlist_does_not_spell_is_refused(
        self, task_store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard is live, not decorative: a clause outside the allowlist never reaches the driver."""
        monkeypatch.setattr(TaskStore, "_ALLOWED_CLAUSES", frozenset({"1=1"}))
        with pytest.raises(ValueError, match="Disallowed WHERE clause: user_id = \\?"):
            await task_store.list_tasks(user_id="alice")
        with pytest.raises(ValueError, match="Disallowed WHERE clause: user_id = \\?"):
            await task_store.count_tasks(user_id="alice")

    async def test_purge_builds_placeholders_from_count_and_binds_the_ids(
        self, task_store: TaskStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`IN (...)` interpolates the marker run only; the ids themselves are the oldest form of
        injection bait, so a task id shaped like a statement is the case worth running."""
        hostile_id = "'); DROP TABLE tasks; --"
        old = Task(id=hostile_id, user_id="alice", goal="finished work", status=TaskStatus.COMPLETED)
        old.created_at = time.time() - 3600
        keeper = Task(user_id="alice", goal="still running", status=TaskStatus.PENDING)
        await task_store.save_task(old)
        await task_store.save_task(keeper)

        seen = _statement_spy(task_store, monkeypatch)
        db = await task_store._conn()
        real_execute = db.execute
        executed: list[tuple[str, Any]] = []

        async def _execute(sql: str, params: Any = ()) -> Any:
            executed.append((sql, params))
            return await real_execute(sql, params)

        monkeypatch.setattr(db, "execute", _execute)
        assert await task_store.purge_finished(older_than_seconds=0) == 1

        assert await task_store.load_task(hostile_id) is None
        assert (await task_store.load_task(keeper.id)) is not None
        assert await task_store.count_tasks() == 1
        for sql, params in [*seen, *executed]:
            if "IN (" in sql:
                assert hostile_id not in sql, sql
                assert sql.count("?") == len(params), (sql, params)


class TestCodingSessionInterpolation:
    async def test_the_filter_travels_as_a_parameter_never_as_text(
        self, session_store: CodingSessionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _statement_spy(session_store, monkeypatch)
        await session_store.list_sessions(user_id=HOSTILE)
        await session_store.count_sessions(user_id=HOSTILE)
        assert seen
        for sql, params in seen:
            assert HOSTILE not in sql, sql
            assert "user_id = ?" in sql, sql
            assert params[0] == HOSTILE, params

    async def test_a_user_id_that_reads_like_sql_returns_nothing_it_should_not(
        self, session_store: CodingSessionManager
    ) -> None:
        await session_store.create_session(CodingSession(user_id="alice", goal="build"))
        assert len(await session_store.list_sessions()) == 1
        assert await session_store.list_sessions(user_id=HOSTILE) == []
        assert await session_store.count_sessions(user_id=HOSTILE) == 0

    async def test_a_clause_the_allowlist_does_not_spell_is_refused(
        self, session_store: CodingSessionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(CodingSessionManager, "_ALLOWED_WHERE", frozenset({"1=1"}))
        with pytest.raises(ValueError, match="Disallowed WHERE clause: user_id = \\?"):
            await session_store.list_sessions(user_id="alice")
        with pytest.raises(ValueError, match="Disallowed WHERE clause: user_id = \\?"):
            await session_store.count_sessions(user_id="alice")


def test_every_b608_annotation_in_the_shipped_code_is_covered_here() -> None:
    """A `# nosec B608` with no test behind it is the drift this project keeps hitting: the annotation
    outlives the property it was written for. The two stores above are the whole annotated surface."""
    annotated = {
        py.relative_to(ROOT).as_posix()
        for py in (ROOT / "raven").rglob("*.py")
        for line in py.read_text(encoding="utf-8-sig").splitlines()
        if "nosec B608" in line
    }
    assert annotated == {"raven/core/coder/session.py", "raven/core/task_engine/store.py"}, sorted(annotated)
