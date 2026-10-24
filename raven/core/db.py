from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from raven.core._json import json
from raven.core.asyncdb import is_postgres_url, normalize_dsn
from raven.core.metrics import timed
from raven.core.migrations import Migrator
from raven.core.models import Message, Session


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self.migrator = Migrator(db_path)

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def connect(self):
        async with self._connect_lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # isolation_level=None: one connection serves every coroutine, and in legacy mode a
            # write sat in an implicit transaction until whichever caller reached commit() first
            # (and was rolled back if that caller failed). Each statement now commits itself, and
            # grouped writes go through _write_tx().
            self._conn = await aiosqlite.connect(str(self.db_path), isolation_level=None)
            self.conn.row_factory = aiosqlite.Row
            for pragma in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA foreign_keys=ON",
                "PRAGMA busy_timeout=5000",
                "PRAGMA synchronous=NORMAL",
            ):
                async with self.conn.execute(pragma):
                    pass
            await self._migrate()

    async def _migrate(self):
        rows = await self._fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        existing = {r[0] for r in rows}

        tables = {
            "sessions": """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'default',
                    agent_skills TEXT DEFAULT '[]',
                    system_prompt TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "messages": """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT CHECK(role IN ('user','assistant','system','tool')),
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "users": """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    display_name TEXT,
                    is_allowed INTEGER DEFAULT 0,
                    role TEXT NOT NULL DEFAULT 'user',
                    pairing_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "plugin_state": """
                CREATE TABLE IF NOT EXISTS plugin_state (
                    plugin_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    PRIMARY KEY (plugin_id, key)
                )
            """,
            "secrets": """
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value_enc TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """,
            "monitors": """
                CREATE TABLE IF NOT EXISTS monitors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('price','http','rss','file','process')),
                    config TEXT NOT NULL DEFAULT '{}',
                    condition TEXT NOT NULL DEFAULT '',
                    cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                    interval_seconds INTEGER NOT NULL DEFAULT 300,
                    notify_channels TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
                    user_id TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT '',
                    last_checked TEXT,
                    last_triggered TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """,
            "rss_seen_items": """
                CREATE TABLE IF NOT EXISTS rss_seen_items (
                    guid TEXT NOT NULL,
                    monitor_id TEXT NOT NULL,
                    seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (guid, monitor_id)
                )
            """,
        }
        for name, ddl in tables.items():
            if name not in existing:
                await self._write(ddl)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_channel ON sessions(channel)",
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_users_channel ON users(channel)",
            "CREATE INDEX IF NOT EXISTS idx_users_external_id ON users(external_id)",
        ]
        for idx in indexes:
            await self._write(idx)

        await self.migrator.migrate()

    async def disconnect(self) -> None:
        async with self._connect_lock:
            conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception as e:
                logger.error("Database close failed: {}", e)

    async def _write(self, sql: str, params: Sequence[Any] = ()) -> None:
        async with self._write_lock:
            await self._exec(sql, params)

    async def _exec(self, sql: str, params: Sequence[Any] = ()) -> None:
        cursor = await self.conn.execute(sql, tuple(params))
        await cursor.close()

    async def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        async with self._write_lock, self.conn.execute(sql, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        async with self._write_lock, self.conn.execute(sql, tuple(params)) as cursor:
            return list(await cursor.fetchall())

    @contextlib.asynccontextmanager
    async def _write_tx(self) -> AsyncIterator[None]:
        """Group several writes into one unit of work on this connection.

        A second BEGIN would raise, and a statement from another task would join this transaction
        and be committed or rolled back with it, so the lock is held for the whole body.
        """
        async with self._write_lock:
            await self._exec("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await self._exec("ROLLBACK")
                raise
            else:
                await self._exec("COMMIT")

    @timed("get_or_create_session")
    async def get_or_create_session(
        self, session_id: str, channel: str, user_id: str, agent_id: str = "default"
    ) -> Session:
        row = await self._fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if row:
            try:
                skills_val = row["agent_skills"]
                skills = json.loads(skills_val) if skills_val and skills_val != "[]" else []
            except (IndexError, KeyError):
                skills = []
            return Session(
                id=row["id"],
                channel=row["channel"],
                user_id=row["user_id"],
                agent_id=row["agent_id"] or "default",
                agent_skills=skills,
                system_prompt=row["system_prompt"],
                created_at=datetime.fromisoformat(row["created_at"])
                if isinstance(row["created_at"], str)
                else datetime.now(UTC),
                updated_at=datetime.fromisoformat(row["updated_at"])
                if isinstance(row["updated_at"], str)
                else datetime.now(UTC),
            )
        now = datetime.now(UTC)
        session = Session(
            id=session_id, channel=channel, user_id=user_id, agent_id=agent_id, created_at=now, updated_at=now
        )
        await self._write(
            "INSERT OR IGNORE INTO sessions "
            "(id, channel, user_id, agent_id, agent_skills, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.channel,
                session.user_id,
                session.agent_id,
                json.dumps(session.agent_skills),
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
            ),
        )
        return session

    @timed("save_message")
    async def save_message(self, msg: Message) -> None:
        async with self._write_tx():
            await self._exec(
                "INSERT OR IGNORE INTO messages "
                "(id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (msg.id, msg.session_id, msg.role, msg.content, json.dumps(msg.metadata), msg.created_at.isoformat()),
            )
            await self._exec(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), msg.session_id),
            )

    @timed("get_session_messages")
    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        result = []
        for row in reversed(list(rows)):
            result.append(
                Message(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(UTC),
                )
            )
        return result

    @timed("find_or_create_user")
    async def find_or_create_user(
        self, channel: str, external_id: str, display_name: str | None = None
    ) -> dict[str, Any]:
        user_id = f"{channel}:{external_id}"
        row = await self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        if row:
            return dict(row)
        await self._write(
            "INSERT OR IGNORE INTO users (id, channel, external_id, display_name, role) VALUES (?, ?, ?, ?, ?)",
            (user_id, channel, external_id, display_name, "user"),
        )
        row = await self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
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

    async def set_user_allowed(self, user_id: str, allowed: bool = True) -> None:
        await self._write("UPDATE users SET is_allowed = ? WHERE id = ?", (1 if allowed else 0, user_id))

    async def set_pairing_code(self, user_id: str, code: str) -> None:
        await self._write("UPDATE users SET pairing_code = ? WHERE id = ?", (code, user_id))

    async def get_user_by_pairing_code(self, code: str) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM users WHERE pairing_code = ?", (code,))
        return dict(row) if row else None

    async def get_pending_pairing_users(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM users WHERE pairing_code IS NOT NULL AND is_allowed = 0")
        return [dict(r) for r in rows]

    async def get_sessions(self, channel: str | None = None) -> list[Session]:
        if channel:
            rows = await self._fetchall(
                "SELECT * FROM sessions WHERE channel = ? ORDER BY updated_at DESC", (channel,)
            )
        else:
            rows = await self._fetchall("SELECT * FROM sessions ORDER BY updated_at DESC")
        result = []
        for r in rows:
            try:
                skills_val = r["agent_skills"]
                skills = json.loads(skills_val) if skills_val and skills_val != "[]" else []
            except (IndexError, KeyError):
                skills = []
            result.append(
                Session(
                    id=r["id"],
                    channel=r["channel"],
                    user_id=r["user_id"],
                    agent_id=r["agent_id"] or "default",
                    agent_skills=skills,
                    system_prompt=r["system_prompt"],
                    created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(UTC),
                    updated_at=datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.now(UTC),
                )
            )
        return result

    async def save_plugin_state(self, plugin_id: str, key: str, value: str) -> None:
        await self._write(
            "INSERT OR REPLACE INTO plugin_state (plugin_id, key, value) VALUES (?, ?, ?)",
            (plugin_id, key, value),
        )

    async def get_plugin_state(self, plugin_id: str, key: str) -> str | None:
        row = await self._fetchone(
            "SELECT value FROM plugin_state WHERE plugin_id = ? AND key = ?", (plugin_id, key)
        )
        return row["value"] if row else None

    @timed("delete_session")
    async def delete_session(self, session_id: str) -> None:
        async with self._write_tx():
            await self._exec("DELETE FROM messages WHERE session_id = ?", (session_id,))
            await self._exec("DELETE FROM sessions WHERE id = ?", (session_id,))

    @timed("replace_session_messages")
    async def replace_session_messages(self, session_id: str, new_messages: list[dict[str, Any]]) -> None:
        async with self._write_tx():
            await self._exec("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for msg in new_messages:
                m = Message(
                    session_id=session_id,
                    role=msg.get("role", "system"),
                    content=msg.get("content", ""),
                    metadata=msg.get("metadata", {}),
                    created_at=msg.get("created_at", datetime.now(UTC)),
                )
                await self._exec(
                    "INSERT INTO messages "
                    "(id, session_id, role, content, metadata, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (m.id, m.session_id, m.role, m.content, json.dumps(m.metadata), m.created_at.isoformat()),
                )

    async def save_secret(self, key: str, value_enc: str) -> None:
        now = datetime.now(UTC).isoformat()
        await self._write(
            "INSERT OR REPLACE INTO secrets (key, value_enc, updated_at) VALUES (?, ?, ?)",
            (key, value_enc, now),
        )

    async def get_secret(self, key: str) -> str | None:
        row = await self._fetchone("SELECT value_enc FROM secrets WHERE key = ?", (key,))
        return row["value_enc"] if row else None

    async def delete_secret(self, key: str) -> None:
        await self._write("DELETE FROM secrets WHERE key = ?", (key,))

    async def list_secrets(self) -> list[str]:
        rows = await self._fetchall("SELECT key FROM secrets ORDER BY key")
        return [r["key"] for r in rows]

    async def health_check(self) -> bool:
        if not self._conn:
            return False
        try:
            # deliberately not _fetchone(): a probe must answer even while the write lock is held
            async with self.conn.execute("SELECT 1") as c:
                await c.fetchone()
            return True
        except Exception as e:
            logger.warning("DB health check failed: {}", e)
            return False


class DatabaseFactory:
    @staticmethod
    def create() -> Database | Any:
        dsn = os.environ.get("DATABASE_URL", "")
        if is_postgres_url(dsn):
            from raven.core.db_postgres import PostgresDatabase

            pg_dsn = normalize_dsn(dsn)
            logger.info("Creating PostgresDatabase (DSN: {}...)", pg_dsn[:40])
            return PostgresDatabase(pg_dsn)
        from raven.core.config import settings

        db_path = settings.resolved_db_path
        logger.info("Creating SQLite Database (path: {})", db_path)
        return Database(db_path)
