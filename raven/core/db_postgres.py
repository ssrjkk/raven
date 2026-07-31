from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import asyncpg
from loguru import logger

from raven.core._json import json
from raven.core.models import Message, Session

_MAX_CONNECT_RETRIES = 3
_CONNECT_RETRY_DELAY_S = 2.0


class _PostgresMigrator:
    def __init__(self, db: PostgresDatabase):
        self.db = db

    async def get_current_version(self) -> int:
        async with self.db._p.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT NOW()
                )
            """)
            row = await conn.fetchrow("SELECT COALESCE(MAX(version), 0) AS v FROM _migrations")
            return row["v"] if row else 0

    async def migrate(self):
        current = await self.get_current_version()
        from raven.core.migrations import _MIGRATIONS

        pending = sorted([m for m in _MIGRATIONS if m.version > current], key=lambda m: m.version)
        if not pending:
            logger.info("Postgres DB is up-to-date (version {})", current)
            return

        async with self.db._p.acquire() as conn, conn.transaction():
                for mig in pending:
                    logger.info("Applying Postgres migration {}: {}", mig.version, mig.description)
                    if mig.sql:
                        await conn.execute(mig.sql)
                    if mig.migrate_fn:
                        await mig.migrate_fn(conn)
                    await conn.execute("INSERT INTO _migrations (version) VALUES ($1)", mig.version)
                    logger.info("Postgres Migration {} applied", mig.version)


class PostgresDatabase:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self.migrator = _PostgresMigrator(self)

    @property
    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected")
        return self._pool

    async def connect(self):
        last_error: Exception | None = None
        for attempt in range(1, _MAX_CONNECT_RETRIES + 1):
            try:
                self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
                await self._create_tables()
                await self.migrator.migrate()
                return
            except (TimeoutError, OSError, asyncpg.PostgresError) as e:
                last_error = e
                if attempt < _MAX_CONNECT_RETRIES:
                    logger.warning(
                        "Postgres connect attempt {}/{} failed: {} — retrying in {}s",
                        attempt,
                        _MAX_CONNECT_RETRIES,
                        e,
                        _CONNECT_RETRY_DELAY_S,
                    )
                    await asyncio.sleep(_CONNECT_RETRY_DELAY_S)
        msg = f"Postgres connect failed after {_MAX_CONNECT_RETRIES} attempts"
        raise RuntimeError(msg) from last_error

    async def reconnect(self):
        await self.disconnect()
        await self.connect()

    async def _create_tables(self):
        async with self._p.acquire() as conn:
            tables = [
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'default',
                    agent_skills TEXT DEFAULT '[]',
                    system_prompt TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    channel TEXT DEFAULT '',
                    role TEXT CHECK(role IN ('user','assistant','system','tool')),
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    display_name TEXT,
                    is_allowed INTEGER DEFAULT 0,
                    role TEXT NOT NULL DEFAULT 'user',
                    pairing_code TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plugin_state (
                    plugin_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    PRIMARY KEY (plugin_id, key)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value_enc TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS monitors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('price','http','rss')),
                    config TEXT NOT NULL,
                    condition TEXT NOT NULL DEFAULT '',
                    cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                    interval_seconds INTEGER NOT NULL DEFAULT 300,
                    notify_channels TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
                    last_checked TIMESTAMP,
                    last_triggered TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS rss_seen_items (
                    guid TEXT NOT NULL,
                    monitor_id TEXT NOT NULL,
                    seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (guid, monitor_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT '',
                    messages TEXT NOT NULL DEFAULT '[]',
                    agent_state TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
            ]
            for ddl in tables:
                await conn.execute(ddl)

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_or_create_session(
        self, session_id: str, channel: str, user_id: str, agent_id: str = "default"
    ) -> Session:
        now = datetime.now(UTC)
        async with self._p.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions "
                "(id, channel, user_id, agent_id, agent_skills, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING",
                session_id,
                channel,
                user_id,
                agent_id,
                "[]",
                now,
                now,
            )
            row = await conn.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
        if row:
            try:
                skills_val = row["agent_skills"]
                skills = json.loads(skills_val) if skills_val and skills_val != "[]" else []
            except (IndexError, KeyError):
                skills = []
            created = row["created_at"]
            updated = row["updated_at"]
            return Session(
                id=row["id"],
                channel=row["channel"],
                user_id=row["user_id"],
                agent_id=row["agent_id"] or "default",
                agent_skills=skills,
                system_prompt=row["system_prompt"],
                created_at=created if isinstance(created, datetime) else datetime.now(UTC),
                updated_at=updated if isinstance(updated, datetime) else datetime.now(UTC),
            )
        now2 = datetime.now(UTC)
        session = Session(
            id=session_id, channel=channel, user_id=user_id, agent_id=agent_id, created_at=now2, updated_at=now2
        )
        async with self._p.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions "
                "(id, channel, user_id, agent_id, agent_skills, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                session.id,
                session.channel,
                session.user_id,
                session.agent_id,
                json.dumps(session.agent_skills),
                session.created_at,
                session.updated_at,
            )
        return session

    async def save_message(self, msg: Message):
        async with self._p.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO messages "
                "(id, session_id, role, content, metadata, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
                msg.id,
                msg.session_id,
                msg.role,
                msg.content,
                json.dumps(msg.metadata),
                msg.created_at,
            )
            await conn.execute(
                "UPDATE sessions SET updated_at = $1 WHERE id = $2",
                datetime.now(UTC),
                msg.session_id,
            )

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        async with self._p.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM messages WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2",
                session_id,
                limit,
            )
        result: list[Message] = []
        for row in reversed(rows):
            metadata_raw = row["metadata"]
            result.append(
                Message(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    metadata=json.loads(metadata_raw) if metadata_raw else {},
                    created_at=row["created_at"] if isinstance(row["created_at"], datetime) else datetime.now(UTC),
                )
            )
        return result

    async def find_or_create_user(
        self, channel: str, external_id: str, display_name: str | None = None
    ) -> dict[str, Any]:
        user_id = f"{channel}:{external_id}"
        async with self._p.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, channel, external_id, display_name, role) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING",
                user_id,
                channel,
                external_id,
                display_name,
                "user",
            )
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if row:
            return dict(row)
        return {
            "id": user_id,
            "channel": channel,
            "external_id": external_id,
            "display_name": display_name,
            "is_allowed": 0,
            "role": "user",
        }

    async def set_user_allowed(self, user_id: str, allowed: bool = True):
        async with self._p.acquire() as conn:
            await conn.execute("UPDATE users SET is_allowed = $1 WHERE id = $2", 1 if allowed else 0, user_id)

    async def set_pairing_code(self, user_id: str, code: str):
        async with self._p.acquire() as conn:
            await conn.execute("UPDATE users SET pairing_code = $1 WHERE id = $2", code, user_id)

    async def get_user_by_pairing_code(self, code: str) -> dict[str, Any] | None:
        async with self._p.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE pairing_code = $1", code)
        return dict(row) if row else None

    async def get_pending_pairing_users(self) -> list[dict[str, Any]]:
        async with self._p.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users WHERE pairing_code IS NOT NULL AND is_allowed = 0")
        return [dict(r) for r in rows]

    async def get_sessions(self, channel: str | None = None) -> list[Session]:
        if channel:
            async with self._p.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM sessions WHERE channel = $1 ORDER BY updated_at DESC", channel)
        else:
            async with self._p.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM sessions ORDER BY updated_at DESC")
        result: list[Session] = []
        for r in rows:
            try:
                skills_val = r["agent_skills"]
                skills = json.loads(skills_val) if skills_val and skills_val != "[]" else []
            except (IndexError, KeyError):
                skills = []
            created = r["created_at"]
            updated = r["updated_at"]
            result.append(
                Session(
                    id=r["id"],
                    channel=r["channel"],
                    user_id=r["user_id"],
                    agent_id=r["agent_id"] or "default",
                    agent_skills=skills,
                    system_prompt=r["system_prompt"],
                    created_at=created if isinstance(created, datetime) else datetime.now(UTC),
                    updated_at=updated if isinstance(updated, datetime) else datetime.now(UTC),
                )
            )
        return result

    async def save_plugin_state(self, plugin_id: str, key: str, value: str):
        async with self._p.acquire() as conn:
            await conn.execute(
                "INSERT INTO plugin_state (plugin_id, key, value) VALUES ($1, $2, $3) "
                "ON CONFLICT (plugin_id, key) DO UPDATE SET value = $3",
                plugin_id,
                key,
                value,
            )

    async def get_plugin_state(self, plugin_id: str, key: str) -> str | None:
        async with self._p.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM plugin_state WHERE plugin_id = $1 AND key = $2", plugin_id, key
            )
        return row["value"] if row else None

    async def delete_session(self, session_id: str):
        async with self._p.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM messages WHERE session_id = $1", session_id)
            await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)

    async def replace_session_messages(self, session_id: str, new_messages: list[dict[str, Any]]):
        async with self._p.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM messages WHERE session_id = $1", session_id)
            for msg in new_messages:
                m = Message(
                    session_id=session_id,
                    channel="",
                    role=msg.get("role", "system"),
                    content=msg.get("content", ""),
                )
                await conn.execute(
                    "INSERT INTO messages (id, session_id, channel, role, content, metadata, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    m.id,
                    m.session_id,
                    m.channel,
                    m.role,
                    m.content,
                    json.dumps(m.metadata),
                    m.created_at,
                )

    async def save_secret(self, key: str, value_enc: str):
        now = datetime.now(UTC)
        async with self._p.acquire() as conn:
            await conn.execute(
                "INSERT INTO secrets (key, value_enc, updated_at) VALUES ($1, $2, $3) "
                "ON CONFLICT (key) DO UPDATE SET value_enc = $2, updated_at = $3",
                key,
                value_enc,
                now,
            )

    async def get_secret(self, key: str) -> str | None:
        async with self._p.acquire() as conn:
            row = await conn.fetchrow("SELECT value_enc FROM secrets WHERE key = $1", key)
        return row["value_enc"] if row else None

    async def delete_secret(self, key: str):
        async with self._p.acquire() as conn:
            await conn.execute("DELETE FROM secrets WHERE key = $1", key)

    async def list_secrets(self) -> list[str]:
        async with self._p.acquire() as conn:
            rows = await conn.fetch("SELECT key FROM secrets ORDER BY key")
        return [r["key"] for r in rows]

    def pool_status(self) -> dict[str, Any]:
        if not self._pool:
            return {"connected": False, "total": 0, "idle": 0, "min_size": 0, "max_size": 0}
        return {
            "connected": True,
            "total": self._pool.get_size(),
            "idle": self._pool.get_idle_size(),
            "min_size": self._pool.get_min_size(),
            "max_size": self._pool.get_max_size(),
        }

    async def validate_pool(self) -> bool:
        if not self._pool:
            return False
        idle = self._pool.get_idle_size()
        if idle == 0:
            return True
        tested = 0
        for _ in range(idle):
            try:
                async with self._p.acquire(timeout=5) as conn:
                    await conn.fetchval("SELECT 1")
                    tested += 1
            except Exception as e:
                logger.debug("Pool connection validation failed: {}", e)
        return tested > 0 or self._pool.get_idle_size() == 0

    async def health_check(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._p.acquire() as conn:
                await conn.fetchval("SELECT 1")
            status = self.pool_status()
            if status["idle"] == 0 and status["total"] >= status["max_size"]:
                logger.warning("Postgres pool exhausted (total={}, max={})", status["total"], status["max_size"])
            return True
        except Exception as e:
            logger.warning("Postgres DB health check failed: {}", e)
            return False
