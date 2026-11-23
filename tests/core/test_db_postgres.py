from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

pytest.importorskip("asyncpg", reason="PostgreSQL tests require asyncpg")

from raven.core.db import Database, DatabaseFactory
from raven.core.db_postgres import _postgres_timestamp, _utc_datetime


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


def test_postgres_timestamp_round_trip_preserves_the_utc_instant():
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    bound = _postgres_timestamp(aware)

    assert bound == datetime(2026, 1, 1, 21, 34, 5)
    assert bound.tzinfo is None
    assert _utc_datetime(bound) == aware
    assert _utc_datetime(bound).tzinfo is UTC


def test_postgres_timestamp_treats_naive_values_as_utc():
    naive = datetime(2026, 1, 2, 3, 4, 5)

    assert _postgres_timestamp(naive) == naive
    assert _utc_datetime(naive) == naive.replace(tzinfo=UTC)
