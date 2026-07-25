from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from raven.core._json import json
from raven.core.auth.models import Role, User
from raven.core.auth.password import hash_password, verify_and_rehash
from raven.core.store import BaseStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '',
    role TEXT DEFAULT 'user',
    password_hash TEXT DEFAULT '',
    api_tokens TEXT DEFAULT '[]',
    is_active INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""


class AuthStore(BaseStore):
    SCHEMA = SCHEMA

    def __init__(self, db_path: Path | str):
        super().__init__(str(db_path))
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def _conn(self) -> aiosqlite.Connection:
        conn = await super()._conn()
        await conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @property
    def db_path(self) -> str:
        return self._path

    async def create_user(self, username: str, password: str = "", display_name: str = "", role: str = "user") -> User:
        now = time.time()
        uid = f"user:{username}"
        pwd_hash = hash_password(password) if password else ""
        await self._execute(
            "INSERT OR IGNORE INTO auth_users "
            "(id, username, display_name, role, password_hash, api_tokens, "
            "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, username, display_name, role, pwd_hash, "[]", 1, now, now),
        )
        await self._commit()
        return User(id=uid, username=username, display_name=display_name, role=Role(role))

    async def _row_to_user(self, row: aiosqlite.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"] or "",
            role=Role(row["role"]),
            password_hash=row["password_hash"] or "",
            api_tokens=json.loads(row["api_tokens"] or "[]"),
            is_active=bool(row["is_active"]),
        )

    async def get_user(self, username: str) -> User | None:
        row = await self._fetchone("SELECT * FROM auth_users WHERE username = ?", (username,))
        if not row:
            return None
        return await self._row_to_user(row)

    async def get_user_by_id(self, user_id: str) -> User | None:
        row = await self._fetchone("SELECT * FROM auth_users WHERE id = ?", (user_id,))
        if not row:
            return None
        return await self._row_to_user(row)

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await self.get_user(username)
        if not user or not user.is_active:
            return None
        if not user.password_hash:
            return None
        new_hash, is_valid = verify_and_rehash(password, user.password_hash)
        if not is_valid:
            return None
        if new_hash:
            await self._execute(
                "UPDATE auth_users SET password_hash = ? WHERE username = ?",
                (new_hash, username),
            )
            await self._commit()
        return user

    async def list_users(self) -> list[User]:
        rows = await self._fetchall("SELECT * FROM auth_users ORDER BY created_at DESC")
        return [await self._row_to_user(r) for r in rows]

    async def update_role(self, username: str, role: str):
        now = time.time()
        await self._execute("UPDATE auth_users SET role = ?, updated_at = ? WHERE username = ?", (role, now, username))
        await self._commit()

    async def update_password(self, username: str, password: str):
        now = time.time()
        pwd_hash = hash_password(password)
        await self._execute(
            "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE username = ?", (pwd_hash, now, username)
        )
        await self._commit()

    async def set_active(self, username: str, active: bool):
        now = time.time()
        await self._execute(
            "UPDATE auth_users SET is_active = ?, updated_at = ? WHERE username = ?",
            (1 if active else 0, now, username),
        )
        await self._commit()
