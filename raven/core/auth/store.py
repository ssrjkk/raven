from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from raven.core._json import json
from raven.core.asyncdb import is_postgres_dsn
from raven.core.auth.models import Role, User
from raven.core.auth.password import dummy_verify, hash_password, verify_and_rehash
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
        super().__init__(db_path)
        if not is_postgres_dsn(db_path):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> str:
        return self._path or ""

    async def create_user(self, username: str, password: str = "", display_name: str = "", role: str = "user") -> User:
        now = time.time()
        uid = f"user:{username}"
        pwd_hash = hash_password(password) if password else ""
        db = await self._conn()
        async with db.transaction():
            rowcount = await db.execute(
                "INSERT INTO auth_users "
                "(id, username, display_name, role, password_hash, api_tokens, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, display_name, role, pwd_hash, "[]", 1, now, now),
            )
            if rowcount is not None and rowcount == 0:
                existing = await self.get_user(username)
                if existing:
                    return existing
        return User(id=uid, username=username, display_name=display_name, role=Role(role))

    async def _row_to_user(self, row: Any) -> User:
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
            # Equalize timing with the real verification path to prevent
            # user-enumeration via response-time differences.
            await asyncio.to_thread(dummy_verify, password)
            return None
        if not user.password_hash:
            await asyncio.to_thread(dummy_verify, password)
            return None
        new_hash, is_valid = await asyncio.to_thread(verify_and_rehash, password, user.password_hash)
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
