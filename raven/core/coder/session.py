from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from raven.core._json import json
from raven.core.coder.models import CodingSession, SessionStatus
from raven.core.store import BaseStore
from raven.utils.performance import measure_latency

SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL,
    project_path TEXT NOT NULL DEFAULT '',
    files TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    history TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cs_user ON coding_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_cs_status ON coding_sessions(status);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS coding_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL,
    project_path TEXT NOT NULL DEFAULT '',
    files TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    history TEXT DEFAULT '[]',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cs_user ON coding_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_cs_status ON coding_sessions(status);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT NOW());
"""


class CodingSessionManager(BaseStore):
    SCHEMA = SCHEMA
    SCHEMA_POSTGRES = SCHEMA_POSTGRES

    def __init__(self, db_path: str | Path):
        super().__init__(db_path)

    _ALLOWED_WHERE = frozenset({"1=1", "user_id = ?"})

    @measure_latency()
    async def create_session(self, session: CodingSession) -> CodingSession:
        await self._execute(
            """INSERT INTO coding_sessions
               (id, user_id, channel, goal, project_path, files, status, history, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id,
                session.user_id,
                session.channel,
                session.goal,
                session.project_path,
                json.dumps(session.files),
                session.status.value,
                json.dumps(session.history),
                session.created_at,
                session.updated_at,
            ),
        )
        await self._commit()
        return session

    @measure_latency()
    async def get_session(self, session_id: str) -> CodingSession | None:
        row = await self._fetchone("SELECT * FROM coding_sessions WHERE id = ?", (session_id,))
        if not row:
            return None
        return self._row_to_session(row)

    @measure_latency()
    async def list_sessions(self, user_id: str | None = None, limit: int = 20, offset: int = 0) -> list[CodingSession]:
        where = "1=1"
        params: list[Any] = []
        if user_id:
            where = "user_id = ?"
            params.append(user_id)
        if where not in self._ALLOWED_WHERE:
            msg = f"Disallowed WHERE clause: {where}"
            raise ValueError(msg)
        rows = await self._fetchall(
            f"SELECT * FROM coding_sessions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._row_to_session(r) for r in rows]

    @measure_latency()
    async def count_sessions(self, user_id: str | None = None) -> int:
        where = "1=1"
        params: list[Any] = []
        if user_id:
            where = "user_id = ?"
            params.append(user_id)
        if where not in self._ALLOWED_WHERE:
            msg = f"Disallowed WHERE clause: {where}"
            raise ValueError(msg)
        row = await self._fetchone(
            f"SELECT COUNT(*) as cnt FROM coding_sessions WHERE {where}",
            params,
        )
        return row["cnt"] if row else 0

    @measure_latency()
    async def update_session(self, session: CodingSession) -> None:
        await self._execute(
            """UPDATE coding_sessions SET goal=?, project_path=?, files=?, status=?, history=?,
               updated_at=? WHERE id=?""",
            (
                session.goal,
                session.project_path,
                json.dumps(session.files),
                session.status.value,
                json.dumps(session.history),
                time.time(),
                session.id,
            ),
        )
        await self._commit()

    async def add_history(self, session_id: str, role: str, content: str) -> None:
        session = await self.get_session(session_id)
        if not session:
            return
        session.history.append({"role": role, "content": content, "time": time.time()})
        session.history = session.history[-100:]
        await self.update_session(session)

    @measure_latency()
    async def delete_session(self, session_id: str) -> None:
        await self._execute("DELETE FROM coding_sessions WHERE id = ?", (session_id,))
        await self._commit()

    def _row_to_session(self, row: Any) -> CodingSession:
        return CodingSession(
            id=row["id"],
            user_id=row["user_id"] or "",
            channel=row["channel"] or "",
            goal=row["goal"],
            project_path=row["project_path"] or "",
            files=json.loads(row["files"]) if row["files"] else [],
            status=SessionStatus(row["status"]),
            history=json.loads(row["history"]) if row["history"] else [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
