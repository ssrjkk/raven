from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from threading import local as thread_local


class AuthStore:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or os.environ.get("DB_PATH", str(Path("data") / "auth.db"))
        self._local = thread_local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                display_name TEXT DEFAULT '', role TEXT DEFAULT 'user',
                password_hash TEXT NOT NULL, is_active INTEGER DEFAULT 1,
                created_at REAL, updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                role TEXT NOT NULL, created_at REAL, expires_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
        """)
        self._conn.commit()
