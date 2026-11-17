"""Eleven statements in this project interpolate SQL with an f-string and carry a `# nosec B608`.

The annotation is a claim, not a fix, so the claim is what these tests measure: the only text that
reaches an interpolated slot is a clause spelled out in `_ALLOWED_CLAUSES` / `_ALLOWED_WHERE`, a run of
`?` markers, or a table and column name from the retention registry, and everything the caller supplied
travels as a bound parameter. The four properties that make that true are asserted directly — a hostile
value never appears in the statement string, the placeholder count always equals the number of bound
parameters, a clause the allowlists do not spell is refused before the statement is built, and a
registry name that is not a bare SQL identifier is refused before a statement exists. If any of them
stops holding, the annotation is lying and these tests are the gate that says so.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from raven.core.coder.models import CodingSession
from raven.core.coder.session import CodingSessionManager
from raven.core.monitor.models import Monitor, MonitorCheck
from raven.core.monitor.store import MonitorStore
from raven.core.retention import POLICIES, RetentionSweeper, TablePolicy, check_identifiers
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


class TestRetentionInterpolation:
    """The sweeper is the third annotated surface and it splices what neither backend can bind.

    `CodingSessionManager` and `TaskStore` interpolate a clause out of their own allowlist; the sweep
    interpolates table and column *names*, which aiosqlite and asyncpg refuse as parameters. So the claim behind its four annotations is measured on both sides of that line: nothing
    a caller owns — a monitor id, a row id, an age cutoff — reaches the statement text, and a registry
    name that is not a bare SQL identifier is refused before a statement exists, which is the sweeper's
    version of the allowlist refusal asserted above.
    """

    async def test_a_hostile_parent_id_is_bound_and_never_spliced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "retention.db"
        store = MonitorStore(path)
        try:
            await store.save_monitor(Monitor(id=HOSTILE, name="injection probe"))
            for offset in range(2):  # past the age window, so the delete-by-age path runs
                await store.save_check(
                    MonitorCheck(monitor_id=HOSTILE, status="ok", checked_at=time.time() - (200 + offset) * 86_400)
                )
            # And rows inside the window: they survive the age pass and force the row cap, which is the
            # path that names ids in an `IN (...)` list — where a bound value could have been spliced
            # into the text instead.
            for offset in range(3):
                await store.save_check(
                    MonitorCheck(monitor_id=HOSTILE, status="ok", checked_at=time.time() - offset * 3_600)
                )
        finally:
            await store.close()

        sweeper = RetentionSweeper(path, telemetry_days=30, telemetry_rows=1, history_days=0)
        db = await sweeper._ensure_db()
        seen: list[tuple[str, tuple[Any, ...]]] = []
        real_execute, real_fetchall = db.execute, db.fetchall

        async def _execute(sql: str, params: Sequence[Any] = ()) -> int | None:
            seen.append((sql, tuple(params)))
            return await real_execute(sql, params)

        async def _fetchall(sql: str, params: Sequence[Any] = ()) -> list[Any]:
            seen.append((sql, tuple(params)))
            return await real_fetchall(sql, params)

        monkeypatch.setattr(db, "execute", _execute)
        monkeypatch.setattr(db, "fetchall", _fetchall)
        try:
            removed = await sweeper.run_once()
        finally:
            await sweeper.stop()

        assert removed == {"monitor_checks": 4}, removed  # 2 by age, then 2 more down to the cap of 1
        assert seen, "the sweep built no statement, so the claims below would measure nothing"
        for sql, params in seen:
            assert HOSTILE not in sql, sql
            assert sql.count("?") == len(params), (sql, params)
        assert any(HOSTILE in params for _, params in seen), "the hostile id never travelled as a parameter"
        assert any("IN (" in sql for sql, _ in seen), "the row cap never ran, so the IN list went unmeasured"

    async def test_a_registry_name_that_is_not_an_identifier_is_refused_before_it_is_spliced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unsanitized registry entry has to stop at the registry, not reach the driver.

        Without the check the hostile name is a working injection: it turns the sweep's DELETE into a
        statement over a table nobody named. The refusal is asserted through a statement spy as well as
        through the exception, because "nothing was deleted" is also what a sweep that skipped the table
        would report — and this install does have the table.
        """
        path = tmp_path / "retention-refuse.db"
        store = MonitorStore(path)
        try:
            await store.save_monitor(Monitor(id="m-1", name="injection probe"))
            await store.save_check(MonitorCheck(monitor_id="m-1", status="ok", checked_at=time.time() - 200 * 86_400))
        finally:
            await store.close()

        monkeypatch.setitem(
            POLICIES,
            "monitor_checks",
            TablePolicy(
                "monitor_checks) WHERE 1=1 --",
                "telemetry",
                "checked_at",
                "epoch_s",
                parent_column="monitor_id",
            ),
        )

        sweeper = RetentionSweeper(path, telemetry_days=30, telemetry_rows=1, history_days=0)
        db = await sweeper._ensure_db()
        built: list[str] = []
        real_execute = db.execute

        async def _spy(sql: str, params: Sequence[Any] = ()) -> int | None:
            built.append(sql)
            return await real_execute(sql, params)

        monkeypatch.setattr(db, "execute", _spy)
        try:
            with pytest.raises(ValueError, match="non-identifier"):
                await sweeper.run_once()
            counts = await db.fetchall("SELECT COUNT(*) AS n FROM monitor_checks")
        finally:
            await sweeper.stop()

        assert not any("DELETE" in sql for sql in built), built
        assert int(counts[0]["n"]) == 1, "the sweep deleted rows while refusing the hostile name"

    def test_the_shipped_registry_satisfies_the_rule_it_is_annotated_for(self) -> None:
        """The negative control: the refusal above came from the name, not from a check that rejects everything.

        The floor is what makes this more than a loop — a registry whose identifiers were never scanned,
        or a pattern matching nothing, would leave both tests above green forever.
        """
        names = {
            name
            for policy in POLICIES.values()
            for name in (policy.table, policy.age_column, policy.parent_column, policy.id_column)
            if name is not None
        }
        assert len(names) >= 30, f"only {len(names)} registry identifiers: the scan is too thin to mean anything"
        for policy in POLICIES.values():
            check_identifiers(policy)


def test_every_b608_annotation_in_the_shipped_code_is_covered_here() -> None:
    """A `# nosec B608` with no test behind it is the drift this project keeps hitting: the annotation
    outlives the property it was written for. The two stores and the sweeper above are the whole
    annotated surface."""
    annotated = {
        py.relative_to(ROOT).as_posix()
        for py in (ROOT / "raven").rglob("*.py")
        for line in py.read_text(encoding="utf-8-sig").splitlines()
        if "nosec B608" in line
    }
    assert annotated == {
        "raven/core/coder/session.py",
        "raven/core/retention.py",
        "raven/core/task_engine/store.py",
    }, sorted(annotated)
