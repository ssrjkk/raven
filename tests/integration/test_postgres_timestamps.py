"""The Postgres columns hold the instant the application meant, checked against a real server.

A `timestamp without time zone` column cannot take the value every writer binds — `datetime.now(UTC)` —
and asyncpg says so at the insert, so a Postgres install could not write a session row or a message row at
all. SQLite has no types to get wrong, and this suite had no server to run against either, which is exactly
how that shipped green: every case skipped, the run reported nothing, and nothing distinguished that from a
pass. It now runs against a server that answers — CI's service, or any `DATABASE_URL` names — and a run that
selects it with none answering fails, because the only honest probe of a type promise is the backend that has
to keep it.

Tables this file creates are named for the run and dropped by it; it never touches another test's data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from raven.core.asyncdb import AsyncDB, PostgresDB, connect_backend
from raven.core.db_postgres import PostgresDatabase
from raven.core.migrations import _MIGRATIONS, apply_pending_migrations
from raven.core.models import Message

pytestmark = pytest.mark.integration


def _run_prefix() -> str:
    """The name these tables are minted with, so it has to be a bare Postgres identifier: a hyphen makes
    every unquoted statement below a syntax error instead of a namespaced name."""
    return f"pgtz{uuid.uuid4().hex[:10]}"


async def _naive_timestamp_columns(db: AsyncDB, tables: list[str]) -> dict[str, list[str]]:
    """Which of these tables still hold a column that refuses a zone-aware value."""
    rows = await db.fetchall(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND data_type = 'timestamp without time zone' "
        "AND table_name = ANY(?::text[])",
        (tables,),
    )
    found: dict[str, list[str]] = {}
    for row in rows:
        found.setdefault(str(row["table_name"]), []).append(str(row["column_name"]))
    return found


async def test_the_writes_the_application_actually_makes_are_accepted(pg_dsn: str) -> None:
    """`get_or_create_session` and `save_message` are the two calls every incoming message runs through, and
    both bind `datetime.now(UTC)`. Nothing else in the suite reaches them on Postgres, which is why a green
    build and a gateway that could not store a conversation were both true at once."""
    session_id = f"{_run_prefix()}-s1"
    db = PostgresDatabase(pg_dsn)
    try:
        await db.connect()
        session = await db.get_or_create_session(session_id, "telegram", "u-1")
        assert session.created_at.tzinfo is not None, "the session row came back without the zone it was written in"

        written = datetime.now(UTC)
        await db.save_message(Message(session_id=session_id, role="user", content="hello", created_at=written))
        messages = await db.get_session_messages(session_id)

        assert len(messages) == 1, messages
        assert messages[0].created_at.tzinfo is not None, "a message came back as a naive datetime"
        assert abs((messages[0].created_at - written).total_seconds()) < 2, (messages[0].created_at, written)
    finally:
        await db.delete_session(session_id)
        await db.disconnect()


async def test_the_schema_the_bootstrap_creates_already_carries_its_zone(pg_dsn: str) -> None:
    """The live catalog is the authority on what a fresh install gets: `PostgresDatabase` runs its own DDL, so
    a naive column in that list is a new install that will refuse the same insert the old one did."""
    db = PostgresDatabase(pg_dsn)
    try:
        await db.connect()
        tables = ["sessions", "messages", "users", "secrets", "rss_seen_items"]
        async with db._p.acquire() as conn:  # the pool the gateway itself uses
            rows = await conn.fetch(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ANY($1::text[]) "
                "AND data_type LIKE 'timestamp%'",
                tables,
            )
        shapes = {(str(r["table_name"]), str(r["column_name"])): str(r["data_type"]) for r in rows}
        assert shapes, "the catalog reported no timestamp columns at all: the probe is broken, not the schema clean"
        missing = sorted(set(tables) - {table for table, _column in shapes})
        assert not missing, f"the catalog named no timestamp column for {missing}, so this says nothing about them"
        naive = sorted(
            f"{table}.{column}" for (table, column), type_name in shapes.items() if "time zone" not in type_name
        )
        assert not naive, f"Postgres DDL still creates a naive TIMESTAMP: {naive}"
    finally:
        await db.disconnect()


async def test_migration_13_retypes_what_an_existing_install_left_naive(pg_dsn: str) -> None:
    """An install from before the schema said TIMESTAMPTZ has columns that cannot take the application's
    writes, and `CREATE TABLE IF NOT EXISTS` will never fix a column that already exists. So the migration is
    tested the way an operator meets it: a real table with a real naive column and a real row, then the
    pending set applied, then the same instant read back and the same write path used again.

    The connection is opened under `Asia/Tokyo` on purpose. `ALTER COLUMN … TYPE TIMESTAMPTZ` without a
    `USING` clause reads a naive wall clock in the session's zone, so on a UTC server — CI's, and most
    containers — the wrong migration still returns the right instant. Under +09:00 it does not, and the row
    comes back nine hours early."""
    table = f"{_run_prefix()}_probe"
    assert "?" not in pg_dsn, "the DSN already carries query options, so appending the zone would corrupt it"
    mig = next(m for m in _MIGRATIONS if m.version == 13)
    assert mig.migrate_fn is not None, "migration 13 vanished"
    # `PostgresDB` rather than `connect_backend`: the latter prefers `DATABASE_URL` over the DSN it is handed,
    # which would drop the zone option and leave this reading the server's own default.
    db = PostgresDB(f"{pg_dsn}?options=-c%20TimeZone=Asia%2FTokyo")
    await db.connect()
    try:
        zone = await db.fetchval("SELECT current_setting('TimeZone')", ())
        assert str(zone) == "Asia/Tokyo", f"the session runs in {zone!r}, so this cannot tell UTC from luck"

        await db.run_script(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, stamped TIMESTAMP)')  # the pre-fix shape  # nosec B608
        await db.execute(
            f"INSERT INTO {table} (id, stamped) VALUES (?, ?)",  # names are this run's own, minted above  # nosec B608
            ("1", datetime(2026, 1, 1)),  # a naive instant, as the pre-fix writers left them
        )
        assert await _naive_timestamp_columns(db, [table]) == {table: ["stamped"]}, "the probe table is not naive"

        await mig.migrate_fn(db)

        rows = await db.fetchall(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? AND column_name = 'stamped'",
            (table,),
        )
        assert str(rows[0]["data_type"]) == "timestamp with time zone", rows

        stored = await db.fetchall(f"SELECT stamped FROM {table}", ())  # nosec B608
        moment = stored[0]["stamped"]
        assert moment.tzinfo is not None, f"the converted column read back naive: {moment!r}"
        assert moment.astimezone(UTC) == datetime(2026, 1, 1, tzinfo=UTC), (
            f"a naive row was re-read as {moment.isoformat()}, not as the UTC instant it was stored as"
        )

        # The restart an operator does after a migration, and part of what this tests: asyncpg caches a
        # prepared statement per connection under its SQL text, so a pool that inserted into the naive column
        # before the ALTER keeps binding against the old shape and refuses the value the migration just
        # allowed. Reconnecting is what the gateway does on deploy, and the same statement must then work.
        await db.close()
        db = PostgresDB(f"{pg_dsn}?options=-c%20TimeZone=Asia%2FTokyo")
        await db.connect()

        await db.execute(
            f"INSERT INTO {table} (id, stamped) VALUES (?, ?)",  # the bind that failed before the fix  # nosec B608
            ("2", datetime.now(UTC)),
        )
        assert len(await db.fetchall(f"SELECT id FROM {table}", ())) == 2  # nosec B608

        await mig.migrate_fn(db)
        assert await _naive_timestamp_columns(db, [table]) == {}, "the second pass found work, so it is not idempotent"
    finally:
        await db.run_script(f'DROP TABLE IF EXISTS "{table}"')
        await db.close()


async def test_migration_13_refuses_a_name_the_catalog_cannot_be_trusted_about(pg_dsn: str) -> None:
    """Neither backend takes an identifier as a parameter, so the migration interpolates what
    `information_schema` answers. A database altered by hand can report a name that is not a bare
    identifier, and that must reach SQL as a refusal rather than as two statements."""
    prefix = _run_prefix()
    table = f"{prefix}_odd;name"
    quoted = f'"{table}"'
    mig = next(m for m in _MIGRATIONS if m.version == 13)
    assert mig.migrate_fn is not None
    db = connect_backend(pg_dsn)
    await db.connect()
    try:
        await db.run_script(f"CREATE TABLE {quoted} (id TEXT PRIMARY KEY, stamped TIMESTAMP)")  # nosec B608
        assert await _naive_timestamp_columns(db, [table]) == {table: ["stamped"]}, (
            "the odd-named column is not in the catalog the migration reads"
        )

        await mig.migrate_fn(db)

        rows = await db.fetchall(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? AND column_name = 'stamped'",
            (table,),
        )
        assert str(rows[0]["data_type"]) == "timestamp without time zone", (
            "an oddly named column was interpolated into DDL instead of refused"
        )
    finally:
        await db.run_script(f"DROP TABLE IF EXISTS {quoted}")


async def test_a_pending_migration_set_leaves_no_naive_columns_anywhere(pg_dsn: str) -> None:
    """The promise is about the whole schema, not about the tables this file happens to name: after a real
    start runs the real migration set, nothing in the public schema should still refuse the bind every
    writer makes."""
    db = connect_backend(pg_dsn)
    await db.connect()
    try:
        await apply_pending_migrations(db)
        rows = await db.fetchall(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = 'timestamp without time zone'"
        )
        leftover = {f"{row['table_name']}.{row['column_name']}" for row in rows}
        assert not leftover, f"these columns still take no zone-aware value: {sorted(leftover)}"
    finally:
        await db.close()
