from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytest.importorskip("asyncpg", reason="PostgreSQL tests require asyncpg")

from raven.core.db import Database, DatabaseFactory


def test_create_returns_database_without_postgres_url():
    with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=True):
        with patch("raven.core.config.settings") as mock_settings:
            mock_settings.resolved_db_path = ":memory:"
            db = DatabaseFactory.create()
            assert isinstance(db, Database)


def test_create_returns_postgres_with_postgres_url():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost:5432/raven"}, clear=True):
        with patch("raven.core.db_postgres.PostgresDatabase") as MockPG:
            DatabaseFactory.create()
            MockPG.assert_called_once_with("postgresql://user:pass@localhost:5432/raven")


def test_create_short_dsn_truncated_in_log():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost:5432/raven"}, clear=True):
        with patch("raven.core.db.logger") as mock_logger:
            with patch("raven.core.db_postgres.PostgresDatabase"):
                DatabaseFactory.create()
                mock_logger.info.assert_called_once()


def test_declared_postgres_ddl_never_holds_a_naive_timestamp() -> None:
    """The writes above bind `datetime.now(UTC)`, and asyncpg refuses that against a bare TIMESTAMP.

    Measured on Postgres 16.14 with asyncpg 0.32: aware -> `timestamp` raises DataError on the first
    session insert, so a real install could not store its first conversation. Every other test here
    mocks the driver and cannot see it, which is why the declared DDL is read as text.
    """
    import inspect
    import re

    from raven.core import migrations
    from raven.core.db_postgres import PostgresDatabase, _PostgresMigrator

    declared = {
        "the core tables": inspect.getsource(PostgresDatabase._create_tables),
        "the migration ledger": inspect.getsource(_PostgresMigrator.get_current_version),
        "MIGRATIONS_TABLE_POSTGRES": migrations.MIGRATIONS_TABLE_POSTGRES,
    }
    for name, text in declared.items():
        assert not re.search(r"\bTIMESTAMP\b", text), f"{name} declares a timestamp without time zone"
