from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from raven.core._json import json
from raven.core.auth.models import Role, User
from raven.core.auth.password import hash_password, verify_password


class AuthStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(str(self.db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("""
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
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        await conn.commit()
        return conn

    async def create_user(self, username: str, password: str = "", display_name: str = "", role: str = "user") -> User:
        now = time.time()
        uid = f"user:{username}"
        pwd_hash = hash_password(password) if password else ""
        conn = await self._conn()
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO auth_users (id, username, display_name, role, password_hash, api_tokens, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, display_name, role, pwd_hash, "[]", 1, now, now),
            )
            await conn.commit()
        finally:
            await conn.close()
        return User(id=uid, username=username, display_name=display_name, role=Role(role))

    async def get_user(self, username: str) -> User | None:
        conn = await self._conn()
        try:
            async with conn.execute("SELECT * FROM auth_users WHERE username = ?", (username,)) as c:
                row = await c.fetchone()
            if not row:
                return None
            return User(
                id=row["id"],
                username=row["username"],
                display_name=row["display_name"] or "",
                role=Role(row["role"]),
                password_hash=row["password_hash"] or "",
                api_tokens=json.loads(row["api_tokens"] or "[]"),
                is_active=bool(row["is_active"]),
            )
        finally:
            await conn.close()

    async def get_user_by_id(self, user_id: str) -> User | None:
        conn = await self._conn()
        try:
            async with conn.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)) as c:
                row = await c.fetchone()
            if not row:
                return None
            return User(
                id=row["id"],
                username=row["username"],
                display_name=row["display_name"] or "",
                role=Role(row["role"]),
                password_hash=row["password_hash"] or "",
                api_tokens=json.loads(row["api_tokens"] or "[]"),
                is_active=bool(row["is_active"]),
            )
        finally:
            await conn.close()

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await self.get_user(username)
        if not user or not user.is_active:
            return None
        if not user.password_hash:
            return None
        if verify_password(password, user.password_hash):
            return user
        return None

    async def list_users(self) -> list[User]:
        conn = await self._conn()
        try:
            async with conn.execute("SELECT * FROM auth_users ORDER BY created_at DESC") as c:
                rows = await c.fetchall()
            return [
                User(
                    id=r["id"],
                    username=r["username"],
                    display_name=r["display_name"] or "",
                    role=Role(r["role"]),
                    is_active=bool(r["is_active"]),
                )
                for r in rows
            ]
        finally:
            await conn.close()

    async def update_role(self, username: str, role: str):
        now = time.time()
        conn = await self._conn()
        try:
            await conn.execute(
                "UPDATE auth_users SET role = ?, updated_at = ? WHERE username = ?", (role, now, username)
            )
            await conn.commit()
        finally:
            await conn.close()

    async def update_password(self, username: str, password: str):
        now = time.time()
        pwd_hash = hash_password(password)
        conn = await self._conn()
        try:
            await conn.execute(
                "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE username = ?", (pwd_hash, now, username)
            )
            await conn.commit()
        finally:
            await conn.close()

    async def set_active(self, username: str, active: bool):
        now = time.time()
        conn = await self._conn()
        try:
            await conn.execute(
                "UPDATE auth_users SET is_active = ?, updated_at = ? WHERE username = ?",
                (1 if active else 0, now, username),
            )
            await conn.commit()
        finally:
            await conn.close()
