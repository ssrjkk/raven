from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

_DEFAULT_DSN = "postgresql://raven:raven@localhost:5432/raven"
"""The service the CI Postgres job starts, used when `DATABASE_URL` names no backend."""

_TYPED_ARG_SOURCES = frozenset({"ARGS", "COMMAND_LINE"})
"""`Config.args_source` names for paths an operator typed, read off the runner: pytest 9 answers
`ArgsSource.ARGS` for `pytest tests/integration` and `ArgsSource.TESTPATHS` for the same directory reached
through `testpaths`, which is the difference between being asked for these tests and being walked past."""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every case that asks for a Postgres handle, so a run can say what it left uncovered.

    The marker is read off the fixture a case binds rather than kept next to it: a case that takes `pg_dsn`
    cannot pass without a server, and a case that does not can. `scripts/check_all.py` deselects the marked
    ones where nothing listens and reports how many it skipped, instead of nominating this directory and
    then failing 17 cases whose only fault is that the machine running the gate has no Postgres. A case that
    starts binding `pg_dsn` is marked by that fact alone; a case that stops binding it is unmarked the same way.
    """
    for item in items:
        if "pg_dsn" in getattr(item, "fixturenames", ()):
            item.add_marker("postgres")


def _suite_selected(config: pytest.Config) -> bool:
    """True when this run asked for the Postgres suite by name.

    `config.args` holds the `testpaths` values too, which is exactly how an ordinary full run reaches this
    directory, so the paths only count when the operator typed them: `args_source` separates the two, and a
    pytest without that attribute falls back to the marker the CI job passes."""
    if "integration" in str(config.getoption("markexpr") or ""):
        return True
    source = getattr(config, "args_source", None)
    if str(getattr(source, "name", source)) not in _TYPED_ARG_SOURCES:
        return False
    here = Path(__file__).parent.resolve()
    for arg in config.args:
        target = Path(str(arg).split("::", 1)[0]).resolve()
        if here == target or here in target.parents:
            return True
    return False


def _no_backend(reason: str, config: pytest.Config) -> NoReturn:
    """Skip when a run walked past this directory, refuse when it asked for these tests by name.

    A selection that executes nothing reported green while the gateway could not write a session row on
    Postgres at all: the suite ran against a server that was not there, every case in it skipped, and the
    verdict said nothing about that. So the loud case is decided by how the run was invoked — `pytest
    tests/integration`, or `-m integration`, the way CI asks — rather than remembered from a log line."""
    if _suite_selected(config):
        pytest.fail(
            f"{reason} — this run selected the Postgres suite, and a suite that skips everything it was "
            "asked to prove is not a pass. Point DATABASE_URL at a server or start the one CI gives it."
        )
    pytest.skip(reason)


@pytest.fixture(scope="session")
async def pg_dsn(request: pytest.FixtureRequest) -> str:
    """A DSN a real Postgres answered on, or the reason this run cannot prove anything about one."""
    from raven.core.asyncdb import postgres_dsn

    dsn = postgres_dsn() or _DEFAULT_DSN
    try:
        import asyncpg
    except ImportError:
        _no_backend("asyncpg not installed (install raven-agent[postgres])", request.config)
    try:
        conn = await asyncpg.connect(dsn, timeout=3)
        await conn.close()
    except Exception as e:
        _no_backend(f"Postgres did not answer at {dsn}: {e}", request.config)
    return dsn


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return path


@pytest.fixture
async def db(db_path: Path) -> AsyncIterator[Any]:
    from raven.core.db import Database

    db = Database(db_path)
    await db.connect()
    yield db
    await db.disconnect()
