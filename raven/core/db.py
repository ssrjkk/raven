from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from raven.core._json import json
from raven.core.migrations import Migrator
from raven.core.models import Message, Session


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self.migrator = Migrator(db_path)

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self._migrate()

    async def _migrate(self):
        async with self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as c:
            rows = await c.fetchall()
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
                    type TEXT NOT NULL CHECK(type IN ('price','http','rss')),
                    config TEXT NOT NULL,
                    condition TEXT NOT NULL DEFAULT '',
                    cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                    interval_seconds INTEGER NOT NULL DEFAULT 300,
                    notify_channels TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
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
                await self.conn.execute(ddl)
        await self.conn.commit()

        await self.migrator.migrate()

    async def disconnect(self):
        if self._conn:
            await self.conn.close()
            self._conn = None

    async def get_or_create_session(
        self, session_id: str, channel: str, user_id: str, agent_id: str = "default"
    ) -> Session:
        async with self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as c:
            row = await c.fetchone()
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
        await self.conn.execute(
            "INSERT OR IGNORE INTO sessions (id, channel, user_id, agent_id, agent_skills, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        await self.conn.commit()
        return session

    async def save_message(self, msg: Message):
        await self.conn.execute(
            "INSERT OR IGNORE INTO messages (id, session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (msg.id, msg.session_id, msg.role, msg.content, json.dumps(msg.metadata), msg.created_at.isoformat()),
        )
        await self.conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), msg.session_id),
        )
        await self.conn.commit()

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        async with self.conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ) as c:
            rows = await c.fetchall()
        result = []
        for row in reversed(list(rows)):
            result.append(
                Message(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    created_at=datetime.fromisoformat(row["created_at"])
                    if row["created_at"]
                    else datetime.now(UTC),
                )
            )
        return result

    async def find_or_create_user(
        self, channel: str, external_id: str, display_name: str | None = None
    ) -> dict[str, Any]:
        user_id = f"{channel}:{external_id}"
        async with self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as c:
            row = await c.fetchone()
        if row:
            return dict(row)
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (id, channel, external_id, display_name, role) VALUES (?, ?, ?, ?, ?)",
            (user_id, channel, external_id, display_name, "user"),
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as c:
            row = await c.fetchone()
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
        await self.conn.execute("UPDATE users SET is_allowed = ? WHERE id = ?", (1 if allowed else 0, user_id))
        await self.conn.commit()

    async def set_pairing_code(self, user_id: str, code: str):
        await self.conn.execute("UPDATE users SET pairing_code = ? WHERE id = ?", (code, user_id))
        await self.conn.commit()

    async def get_user_by_pairing_code(self, code: str) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM users WHERE pairing_code = ?", (code,)) as c:
            row = await c.fetchone()
        return dict(row) if row else None

    async def get_pending_pairing_users(self) -> list[dict[str, Any]]:
        async with self.conn.execute("SELECT * FROM users WHERE pairing_code IS NOT NULL AND is_allowed = 0") as c:
            rows = await c.fetchall()
        return [dict(r) for r in rows]

    async def get_sessions(self, channel: str | None = None) -> list[Session]:
        if channel:
            async with self.conn.execute(
                "SELECT * FROM sessions WHERE channel = ? ORDER BY updated_at DESC", (channel,)
            ) as c:
                rows = await c.fetchall()
        else:
            async with self.conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC") as c:
                rows = await c.fetchall()
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
                    created_at=datetime.fromisoformat(r["created_at"])
                    if r["created_at"]
                    else datetime.now(UTC),
                    updated_at=datetime.fromisoformat(r["updated_at"])
                    if r["updated_at"]
                    else datetime.now(UTC),
                )
            )
        return result

    async def save_plugin_state(self, plugin_id: str, key: str, value: str):
        await self.conn.execute(
            "INSERT OR REPLACE INTO plugin_state (plugin_id, key, value) VALUES (?, ?, ?)",
            (plugin_id, key, value),
        )
        await self.conn.commit()

    async def get_plugin_state(self, plugin_id: str, key: str) -> str | None:
        async with self.conn.execute(
            "SELECT value FROM plugin_state WHERE plugin_id = ? AND key = ?", (plugin_id, key)
        ) as c:
            row = await c.fetchone()
        return row["value"] if row else None

    async def delete_session(self, session_id: str):
        await self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self.conn.commit()

    async def replace_session_messages(self, session_id: str, new_messages: list[dict[str, Any]]):
        await self.conn.execute("BEGIN")
        await self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for msg in new_messages:
            m = Message(
                session_id=session_id,
                channel="",
                role=msg.get("role", "system"),
                content=msg.get("content", ""),
            )
            await self.conn.execute(
                "INSERT INTO messages (id, session_id, channel, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (m.id, m.session_id, m.channel, m.role, m.content, m.metadata, m.created_at.isoformat()),
            )
        await self.conn.execute("COMMIT")

    async def save_secret(self, key: str, value_enc: str):
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            "INSERT OR REPLACE INTO secrets (key, value_enc, updated_at) VALUES (?, ?, ?)",
            (key, value_enc, now),
        )
        await self.conn.commit()

    async def get_secret(self, key: str) -> str | None:
        async with self.conn.execute(
            "SELECT value_enc FROM secrets WHERE key = ?", (key,)
        ) as c:
            row = await c.fetchone()
        return row["value_enc"] if row else None

    async def delete_secret(self, key: str):
        await self.conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
        await self.conn.commit()

    async def list_secrets(self) -> list[str]:
        async with self.conn.execute("SELECT key FROM secrets ORDER BY key") as c:
            rows = await c.fetchall()
        return [r["key"] for r in rows]

    async def health_check(self) -> bool:
        if not self._conn:
            return False
        try:
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
        if dsn.startswith("postgresql://"):
            from raven.core.db_postgres import PostgresDatabase

            logger.info("Creating PostgresDatabase (DSN: {}...)", dsn[:40])
            return PostgresDatabase(dsn)
        from raven.core.config import settings

        db_path = settings.resolved_db_path
        logger.info("Creating SQLite Database (path: {})", db_path)
        return Database(db_path)
