from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from raven.core._json import json
from raven.core.coder.models import CodingSession, SessionStatus

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn  # type: ignore[no-any-return]


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
"""


class CodingSessionManager:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        conn = sqlite3.connect(self._path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._path)

    def create_session(self, session: CodingSession) -> CodingSession:
        conn = self._conn()
        conn.execute(
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
        conn.commit()
        return session

    def get_session(self, session_id: str) -> CodingSession | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM coding_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    _ALLOWED_WHERE = frozenset({"1=1", "user_id = ?"})

    def list_sessions(self, user_id: str | None = None, limit: int = 20, offset: int = 0) -> list[CodingSession]:
        conn = self._conn()
        where = "1=1"
        params: list[Any] = []
        if user_id:
            where = "user_id = ?"
            params.append(user_id)
        if where not in self._ALLOWED_WHERE:
            raise ValueError(f"Disallowed WHERE clause: {where}")
        rows = conn.execute(
            f"SELECT * FROM coding_sessions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608 — validated against _ALLOWED_WHERE
            (*params, limit, offset),
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def update_session(self, session: CodingSession) -> None:
        conn = self._conn()
        conn.execute(
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
        conn.commit()

    def add_history(self, session_id: str, role: str, content: str) -> None:
        session = self.get_session(session_id)
        if not session:
            return
        session.history.append({"role": role, "content": content, "time": time.time()})
        session.history = session.history[-100:]
        self.update_session(session)

    def delete_session(self, session_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM coding_sessions WHERE id = ?", (session_id,))
        conn.commit()

    def _row_to_session(self, row: sqlite3.Row) -> CodingSession:
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
