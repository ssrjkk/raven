from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("asyncpg", reason="PostgreSQL tests require asyncpg")

import asyncpg

from raven.core.db_postgres import PostgresDatabase


@pytest.fixture
def conn() -> AsyncMock:
    c = AsyncMock(spec=asyncpg.Connection)
    c.fetchval = AsyncMock(return_value=1)
    return c


@pytest.fixture
def acquire_cm(conn: AsyncMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.fixture
def mock_pool(acquire_cm: AsyncMock) -> MagicMock:
    pool = MagicMock(spec=asyncpg.Pool)
    pool.get_size.return_value = 3
    pool.get_idle_size.return_value = 2
    pool.get_min_size.return_value = 1
    pool.get_max_size.return_value = 10
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


@pytest.fixture
def db(mock_pool: MagicMock) -> PostgresDatabase:
    d = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
    d._pool = mock_pool
    return d


class TestPoolStatus:
    async def test_pool_status_returns_metrics(self, db: PostgresDatabase):
        status = db.pool_status()
        assert status["connected"] is True
        assert status["total"] == 3
        assert status["idle"] == 2
        assert status["min_size"] == 1
        assert status["max_size"] == 10

    async def test_pool_status_when_not_connected(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        status = db.pool_status()
        assert status["connected"] is False
        assert status["total"] == 0
        assert status["idle"] == 0

    async def test_validate_pool_acquires_connections(self, db: PostgresDatabase, mock_pool: MagicMock):
        result = await db.validate_pool()
        assert result is True
        assert mock_pool.acquire.called


class TestHealthCheck:
    async def test_health_check_returns_true(self, db: PostgresDatabase):
        assert await db.health_check() is True

    async def test_health_check_returns_false_when_no_pool(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        assert await db.health_check() is False

    async def test_health_check_returns_false_on_error(self, db: PostgresDatabase, mock_pool: MagicMock, acquire_cm: AsyncMock):
        conn = AsyncMock(spec=asyncpg.Connection)
        conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("connection lost"))
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        assert await db.health_check() is False


class TestValidatePool:
    async def test_validate_pool_returns_false_when_no_pool(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        assert await db.validate_pool() is False

    async def test_validate_pool_returns_true_when_idle_zero(self, mock_pool: MagicMock):
        mock_pool.get_idle_size.return_value = 0
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        db._pool = mock_pool
        assert await db.validate_pool() is True


class TestConnectRetry:
    async def test_connect_succeeds_first_attempt(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        db.migrator = AsyncMock()
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
            with patch.object(db, "_create_tables", new_callable=AsyncMock):
                await db.connect()
                assert mock_create_pool.call_count == 1

    async def test_connect_retries_on_failure(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        db.migrator = AsyncMock()
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
            mock_create_pool.side_effect = [OSError("connection refused"), "pool"]
            with patch.object(db, "_create_tables", new_callable=AsyncMock):
                await db.connect()
                assert mock_create_pool.call_count == 2

    async def test_connect_raises_after_max_retries(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        db.migrator = AsyncMock()
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
            mock_create_pool.side_effect = OSError("connection refused")
            with pytest.raises(RuntimeError, match="failed after 3 attempts"):
                await db.connect()

    async def test_reconnect_calls_disconnect_and_connect(self):
        db = PostgresDatabase("postgresql://user:pass@localhost:5432/test")
        db.migrator = AsyncMock()
        with patch.object(db, "disconnect", new_callable=AsyncMock) as mock_disconnect:
            with patch.object(db, "connect", new_callable=AsyncMock) as mock_connect:
                await db.reconnect()
                mock_disconnect.assert_called_once()
                mock_connect.assert_called_once()
