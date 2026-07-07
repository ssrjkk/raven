from __future__ import annotations

import os
from unittest.mock import patch

import pytest

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
            result = DatabaseFactory.create()
            MockPG.assert_called_once_with("postgresql://user:pass@localhost:5432/raven")


def test_create_short_dsn_truncated_in_log():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost:5432/raven"}, clear=True):
        with patch("raven.core.db.logger") as mock_logger:
            with patch("raven.core.db_postgres.PostgresDatabase"):
                DatabaseFactory.create()
                mock_logger.info.assert_called_once()
