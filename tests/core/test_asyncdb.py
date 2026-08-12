from unittest.mock import patch

from raven.core.asyncdb import (
    PostgresDB,
    SQLiteDB,
    connect_backend,
    is_postgres_dsn,
    is_postgres_url,
    normalize_dsn,
    postgres_dsn,
)


def test_is_postgres_url_plain_scheme():
    assert is_postgres_url("postgresql://user:pass@localhost:5432/raven")
    assert is_postgres_url("PostgreSQL://user@host/db")
    assert not is_postgres_url("data/raven.db")
    assert not is_postgres_url("")
    assert not is_postgres_url("sqlite:///data/raven.db")


def test_is_postgres_url_sqlalchemy_scheme():
    assert is_postgres_url("postgresql+asyncpg://user:pass@localhost:5432/raven_test")
    assert is_postgres_url("postgresql+psycopg://user@host/db")
    assert is_postgres_url("  postgresql+asyncpg://user@host/db  ")


def test_normalize_dsn_strips_driver_suffix():
    assert (
        normalize_dsn("postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
        == "postgresql://raven:raven@localhost:5432/raven_test"
    )
    assert (
        normalize_dsn("postgresql://raven:raven@localhost:5432/raven")
        == "postgresql://raven:raven@localhost:5432/raven"
    )


def test_postgres_dsn_prefers_normalized_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    assert postgres_dsn() == "postgresql://raven:raven@localhost:5432/raven_test"


def test_postgres_dsn_empty_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert postgres_dsn() is None


def test_is_postgres_dsn_handles_sqlalchemy_scheme():
    assert is_postgres_dsn("postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    assert not is_postgres_dsn("data/raven.db")


def test_connect_backend_uses_env_dsn(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    db = connect_backend("data/raven.db")
    assert isinstance(db, PostgresDB)
    assert db.dsn == "postgresql://raven:raven@localhost:5432/raven_test"


def test_connect_backend_uses_dsn_argument():
    db = connect_backend(dsn="postgresql+asyncpg://user@host:5432/raven")
    assert isinstance(db, PostgresDB)
    assert db.dsn == "postgresql://user@host:5432/raven"


def test_connect_backend_dsn_db_path():
    db = connect_backend("postgresql://user@host:5432/raven")
    assert isinstance(db, PostgresDB)


def test_connect_backend_sqlite_fallback():
    db = connect_backend("data/raven.db")
    assert isinstance(db, SQLiteDB)
    assert db._path == "data/raven.db"


def test_connect_backend_requires_path_without_dsn():
    with patch.dict("os.environ", {"DATABASE_URL": ""}, clear=True):
        try:
            connect_backend(None)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for missing db_path")
