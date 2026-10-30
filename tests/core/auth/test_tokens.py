from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from raven.core.auth.store import AuthStore
from raven.core.auth.tokens import TokenManager
from raven.core.migrations import apply_pending_migrations


class TestTokenManagerMemory:
    @pytest.fixture
    def mgr(self) -> TokenManager:
        return TokenManager()

    async def test_create_and_validate(self, mgr: TokenManager):
        token = await mgr.create_token("user1", "admin")
        data = await mgr.validate_token(token)
        assert data is not None
        assert data["user_id"] == "user1"
        assert data["role"] == "admin"

    async def test_validate_invalid_token(self, mgr: TokenManager):
        assert await mgr.validate_token("nonexistent") is None

    async def test_validate_expired_token(self, mgr: TokenManager):
        token = await mgr.create_token("user1", "user", ttl_seconds=0)
        assert await mgr.validate_token(token) is None

    async def test_revoke_token(self, mgr: TokenManager):
        token = await mgr.create_token("user1", "user")
        await mgr.revoke_token(token)
        assert await mgr.validate_token(token) is None

    async def test_revoke_nonexistent(self, mgr: TokenManager):
        await mgr.revoke_token("does_not_exist")

    async def test_revoke_user_tokens(self, mgr: TokenManager):
        t1 = await mgr.create_token("user1", "user")
        t2 = await mgr.create_token("user1", "user")
        t3 = await mgr.create_token("user2", "user")
        await mgr.revoke_user_tokens("user1")
        assert await mgr.validate_token(t1) is None
        assert await mgr.validate_token(t2) is None
        assert await mgr.validate_token(t3) is not None


class TestTokenManagerStore:
    @pytest.fixture
    async def store(self, tmp_path: Path):
        s = AuthStore(tmp_path / "auth.db")
        yield s
        await s.close()

    async def test_session_survives_a_new_manager(self, store: AuthStore):
        first = TokenManager()
        first.bind(store)
        token = await first.create_token("user:alice", "user")

        second = TokenManager()
        second.bind(store)
        data = await second.validate_token(token)
        assert data is not None
        assert data["user_id"] == "user:alice"

    async def test_database_stores_only_the_digest(self, store: AuthStore):
        token = await store.create_session("user:alice", "user")
        rows = await store._fetchall("SELECT token_hash FROM auth_sessions")
        assert [row["token_hash"] for row in rows] == [
            hashlib.sha256(token.encode("utf-8")).hexdigest()
        ]
        assert token not in {row["token_hash"] for row in rows}

    async def test_expired_session_is_gone(self, store: AuthStore):
        token = await store.create_session("user:alice", "user", ttl_seconds=-1)
        assert await store.get_session(token) is None
        assert await store._fetchval("SELECT COUNT(*) FROM auth_sessions") == 0

    async def test_revoke_session(self, store: AuthStore):
        token = await store.create_session("user:alice", "user")
        await store.revoke_session(token)
        assert await store.get_session(token) is None

    async def test_deactivated_user_session_rejected(self, store: AuthStore):
        await store.create_user("alice", "Secret123!")
        token = await store.create_session("user:alice", "user")
        assert await store.get_session(token) is not None
        await store.set_active("alice", False)
        assert await store.get_session(token) is None

    async def test_deactivation_revokes_every_session(self, store: AuthStore):
        await store.create_user("alice", "Secret123!")
        t1 = await store.create_session("user:alice", "user")
        t2 = await store.create_session("user:alice", "user")
        await store.revoke_all_user_sessions("user:alice")
        assert await store.get_session(t1) is None
        assert await store.get_session(t2) is None

    async def test_unknown_identity_without_account_row_still_valid(self, store: AuthStore):
        # OAuth callbacks mint a session for an identity that has no auth_users row.
        token = await store.create_session("oauth:github:42", "user")
        data = await store.get_session(token)
        assert data is not None
        assert data["user_id"] == "oauth:github:42"

    async def test_created_at_and_expiry_are_reported(self, store: AuthStore):
        before = time.time()
        token = await store.create_session("user:alice", "user", ttl_seconds=60)
        data = await store.get_session(token)
        assert data is not None
        assert data["created_at"] >= before
        assert data["expires_at"] - data["created_at"] == pytest.approx(60, abs=1)

    async def test_the_migration_revokes_sessions_stored_as_credentials(self, store: AuthStore):
        await store.create_session("user:alice", "user")
        db = await store._conn()
        await db.run_script("ALTER TABLE auth_sessions RENAME COLUMN token_hash TO token")
        await db.execute("DELETE FROM _migrations WHERE version = 12")
        await db.commit()

        await apply_pending_migrations(db)

        columns = {row["name"] for row in await db.fetchall("PRAGMA table_info(auth_sessions)")}
        assert "token_hash" in columns and "token" not in columns
        assert await store._fetchval("SELECT COUNT(*) FROM auth_sessions") == 0
