from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core._json import json
from raven.core.asyncdb import AsyncDB, is_postgres_dsn
from raven.core.auth.models import Role, User
from raven.core.auth.password import dummy_verify, hash_password, verify_and_rehash
from raven.core.store import BaseStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    email_verified INTEGER DEFAULT 0,
    role TEXT DEFAULT 'user',
    password_hash TEXT DEFAULT '',
    api_tokens TEXT DEFAULT '[]',
    is_active INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS auth_email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_email_tokens_expires_at ON auth_email_tokens(expires_at);
CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""

_TOKEN_TTL_SECONDS = 86400
_PURGE_SESSIONS = "DELETE FROM auth_sessions WHERE expires_at <= ?"
_PURGE_EMAIL_TOKENS = "DELETE FROM auth_email_tokens WHERE expires_at <= ?"
# `create_user` mints every local id as f"user:{username}", so a session whose user_id lacks that
# prefix is an identity the table was never told about: an OAuth subject.
_LOCAL_ID_PREFIX = "user:"


async def _purge_expired_on(connection: AsyncDB, now: float) -> dict[str, int]:
    """Delete credentials past their expiry. Expiry was only ever consulted when a row was read,
    so an abandoned login left a permanent row in the table that decides whether a caller is
    revoked, and a verification link nobody clicked was never reached by the spend-time delete."""
    sessions = await connection.execute(_PURGE_SESSIONS, (now,)) or 0
    tokens = await connection.execute(_PURGE_EMAIL_TOKENS, (now,)) or 0
    return {"sessions": sessions, "email_tokens": tokens}


def _token_digest(token: str) -> str:
    """Digest a verification credential so the stored row cannot be spent as the credential is."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore(BaseStore):
    SCHEMA = SCHEMA

    def __init__(self, db_path: Path | str):
        super().__init__(db_path)
        if not is_postgres_dsn(db_path):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> str:
        return self._path or ""

    async def _post_schema(self, connection: AsyncDB) -> None:
        removed = await _purge_expired_on(connection, time.time())
        total = removed["sessions"] + removed["email_tokens"]
        if total:
            logger.info("AuthStore: dropped {} expired credential rows", total)

    async def purge_expired(self) -> dict[str, int]:
        """Drop expired sessions and email tokens. Returns how many rows each table lost."""
        db = await self._conn()
        async with db.transaction():
            return await _purge_expired_on(db, time.time())

    async def create_user(
        self, username: str, password: str = "", display_name: str = "", email: str = "", role: str = "user"
    ) -> User:
        now = time.time()
        uid = f"{_LOCAL_ID_PREFIX}{username}"
        pwd_hash = hash_password(password) if password else ""
        db = await self._conn()
        async with db.transaction():
            rowcount = await db.execute(
                "INSERT INTO auth_users "
                "(id, username, display_name, email, email_verified, role, password_hash, api_tokens, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, display_name, email, 0, role, pwd_hash, "[]", 1, now, now),
            )
            if rowcount is not None and rowcount == 0:
                existing = await self.get_user(username)
                if existing:
                    return existing
        return User(
            id=uid, username=username, display_name=display_name, email=email, email_verified=False, role=Role(role)
        )

    async def _row_to_user(self, row: Any) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"] or "",
            email=row["email"] or None,
            email_verified=bool(row["email_verified"]),
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
        # The role a token carries was copied from the account when it was issued, so a promotion
        # or a demotion is invisible to the tokens already out there until they are dropped.
        await self.revoke_all_user_sessions(f"{_LOCAL_ID_PREFIX}{username}")

    async def update_password(self, username: str, password: str):
        now = time.time()
        pwd_hash = hash_password(password)
        await self._execute(
            "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE username = ?", (pwd_hash, now, username)
        )
        await self._commit()
        # Changing the password is what an operator does when a credential leaked; leaving the
        # sessions issued under the old one alive for another `_TOKEN_TTL_SECONDS` would not end the leak.
        await self.revoke_all_user_sessions(f"{_LOCAL_ID_PREFIX}{username}")

    async def set_active(self, username: str, active: bool):
        now = time.time()
        await self._execute(
            "UPDATE auth_users SET is_active = ?, updated_at = ? WHERE username = ?",
            (1 if active else 0, now, username),
        )
        await self._commit()

    async def create_email_verification_token(self, user_id: str) -> str:
        """Issue a verification credential. Only its digest is stored: the row is not a copy of
        something that can be spent by whoever reads the database."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        db = await self._conn()
        async with db.transaction():
            await _purge_expired_on(db, now)
            await db.execute(
                "INSERT INTO auth_email_tokens (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_digest(token), user_id, now, now + _TOKEN_TTL_SECONDS),
            )
        return token

    async def verify_email_token(self, token: str) -> bool:
        digest = _token_digest(token)
        row = await self._fetchone(
            "SELECT user_id, expires_at FROM auth_email_tokens WHERE token_hash = ?",
            (digest,),
        )
        if not row:
            return False
        if row["expires_at"] < time.time():
            await self._execute("DELETE FROM auth_email_tokens WHERE token_hash = ?", (digest,))
            await self._commit()
            return False
        user_id = row["user_id"]
        now = time.time()
        db = await self._conn()
        async with db.transaction():
            await db.execute(
                "UPDATE auth_users SET email_verified = 1, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
            await db.execute("DELETE FROM auth_email_tokens WHERE token_hash = ?", (digest,))
        return True

    async def has_pending_email_verification(self, user_id: str) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM auth_email_tokens WHERE user_id = ? AND expires_at > ?",
            (user_id, time.time()),
        )
        return row is not None

    async def _ensure_external_identity(self, user_id: str, role: str) -> None:
        """Give an identity that arrives from outside the table a row of its own.

        An OAuth subject used to be issued a token with nothing behind it: the session could not be
        revoked by deactivating anyone, because there was nobody to deactivate, and `get_session`
        had to treat a missing account row as normal — which is the same shape as a local account
        that has been deleted.
        """
        if user_id.startswith(_LOCAL_ID_PREFIX):
            return
        if await self.get_user_by_id(user_id):
            return
        now = time.time()
        db = await self._conn()
        async with db.transaction():
            await db.execute(
                "INSERT INTO auth_users "
                "(id, username, display_name, email, email_verified, role, password_hash, api_tokens, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, '', 0, ?, '', '[]', 1, ?, ?)",
                (user_id, user_id, user_id, role, now, now),
            )

    async def create_session(self, user_id: str, role: str, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
        """Issue a bearer token and store only its digest, so a database reader cannot replay it."""
        await self._ensure_external_identity(user_id, role)
        token = secrets.token_urlsafe(32)
        now = time.time()
        db = await self._conn()
        async with db.transaction():
            await _purge_expired_on(db, now)
            await db.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (_token_digest(token), user_id, role, now, now + ttl_seconds),
            )
        return token

    async def get_session(self, token: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            """SELECT s.user_id, s.role, s.created_at, s.expires_at, u.id AS user_row, u.is_active
               FROM auth_sessions s LEFT JOIN auth_users u ON u.id = s.user_id
               WHERE s.token_hash = ?""",
            (_token_digest(token),),
        )
        if not row:
            return None
        if row["expires_at"] <= time.time():
            await self.revoke_session(token)
            return None
        # A token is only as live as the account behind it. `create_session` guarantees the row
        # exists for every identity it issues to, so a missing row here means the account is gone.
        if row["user_row"] is None or not row["is_active"]:
            return None
        return {
            "user_id": row["user_id"],
            "role": row["role"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    async def revoke_session(self, token: str) -> None:
        await self._execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_digest(token),))
        await self._commit()

    async def revoke_all_user_sessions(self, user_id: str) -> int:
        rowcount = await self._execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        await self._commit()
        return rowcount or 0

    async def count_user_sessions(self, user_id: str) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id = ?", (user_id,))
        return int(row["n"]) if row else 0
