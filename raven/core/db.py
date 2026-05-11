from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiosqlite
from loguru import logger
from raven.core.models import Message, Session
from raven.core.migrations import Migrator


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self.migrator = Migrator(db_path)

    async def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._migrate()

    async def _migrate(self):
        await self.migrator.migrate()
        async with self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as c:
            rows = await c.fetchall()
            existing = {r[0] for r in rows}

        tables = {
            "sessions": """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'default',
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
        }
        for name, ddl in tables.items():
            if name not in existing:
                await self._conn.execute(ddl)
        await self._conn.commit()

    async def disconnect(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def get_or_create_session(self, session_id: str, channel: str, user_id: str, agent_id: str = "default") -> Session:
        async with self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as c:
            row = await c.fetchone()
        if row:
            return Session(
                id=row["id"],
                channel=row["channel"],
                user_id=row["user_id"],
                agent_id=row["agent_id"] or "default",
                system_prompt=row["system_prompt"],
                created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else datetime.now(timezone.utc),
                updated_at=datetime.fromisoformat(row["updated_at"]) if isinstance(row["updated_at"], str) else datetime.now(timezone.utc),
            )
        now = datetime.now(timezone.utc)
        session = Session(id=session_id, channel=channel, user_id=user_id, agent_id=agent_id, created_at=now, updated_at=now)
        await self._conn.execute(
            "INSERT INTO sessions (id, channel, user_id, agent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session.id, session.channel, session.user_id, session.agent_id, session.created_at.isoformat(), session.updated_at.isoformat()),
        )
        await self._conn.commit()
        return session

    async def save_message(self, msg: Message):
        await self._conn.execute(
            "INSERT OR IGNORE INTO messages (id, session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (msg.id, msg.session_id, msg.role, msg.content, json.dumps(msg.metadata), msg.created_at.isoformat()),
        )
        await self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), msg.session_id),
        )
        await self._conn.commit()

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ) as c:
            rows = await c.fetchall()
        result = []
        for row in reversed(rows):
            result.append(Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
            ))
        return result

    async def find_or_create_user(self, channel: str, external_id: str, display_name: str | None = None) -> dict[str, Any]:
        user_id = f"{channel}:{external_id}"
        async with self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as c:
            row = await c.fetchone()
        if row:
            return dict(row)
        await self._conn.execute(
            "INSERT INTO users (id, channel, external_id, display_name) VALUES (?, ?, ?, ?)",
            (user_id, channel, external_id, display_name),
        )
        await self._conn.commit()
        return {"id": user_id, "channel": channel, "external_id": external_id, "display_name": display_name, "is_allowed": 0}

    async def set_user_allowed(self, user_id: str, allowed: bool = True):
        await self._conn.execute("UPDATE users SET is_allowed = ? WHERE id = ?", (1 if allowed else 0, user_id))
        await self._conn.commit()

    async def set_pairing_code(self, user_id: str, code: str):
        await self._conn.execute("UPDATE users SET pairing_code = ? WHERE id = ?", (code, user_id))
        await self._conn.commit()

    async def get_user_by_pairing_code(self, code: str) -> dict[str, Any] | None:
        async with self._conn.execute("SELECT * FROM users WHERE pairing_code = ?", (code,)) as c:
            row = await c.fetchone()
        return dict(row) if row else None

    async def get_pending_pairing_users(self) -> list[dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM users WHERE pairing_code IS NOT NULL AND is_allowed = 0") as c:
            rows = await c.fetchall()
        return [dict(r) for r in rows]

    async def get_sessions(self, channel: str | None = None) -> list[Session]:
        if channel:
            async with self._conn.execute("SELECT * FROM sessions WHERE channel = ? ORDER BY updated_at DESC", (channel,)) as c:
                rows = await c.fetchall()
        else:
            async with self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC") as c:
                rows = await c.fetchall()
        return [Session(
            id=r["id"], channel=r["channel"], user_id=r["user_id"],
            agent_id=r["agent_id"] or "default", system_prompt=r["system_prompt"],
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.now(timezone.utc),
        ) for r in rows]

    async def save_plugin_state(self, plugin_id: str, key: str, value: str):
        await self._conn.execute(
            "INSERT OR REPLACE INTO plugin_state (plugin_id, key, value) VALUES (?, ?, ?)",
            (plugin_id, key, value),
        )
        await self._conn.commit()

    async def get_plugin_state(self, plugin_id: str, key: str) -> str | None:
        async with self._conn.execute("SELECT value FROM plugin_state WHERE plugin_id = ? AND key = ?", (plugin_id, key)) as c:
            row = await c.fetchone()
        return row["value"] if row else None

    async def delete_session(self, session_id: str):
        await self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._conn.commit()

    async def health_check(self) -> bool:
        if not self._conn:
            return False
        try:
            async with self._conn.execute("SELECT 1") as c:
                await c.fetchone()
            return True
        except Exception:
            return False
