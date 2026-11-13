"""Expired credentials must leave the tables that decide whether a caller is revoked.

Measured on a live install: 3471 rows in ``auth_sessions``, 3096 of them already past
``expires_at``. Nothing ever deleted them — expiry was only consulted when a row was read,
so an abandoned login left a permanent row and the revocation table grew with every login for
the whole life of the database. ``auth_email_tokens`` had the same gap: a verification link that
is never clicked is never spent, so its row is never reached by the spend-time DELETE either.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from raven.core.auth.store import AuthStore, _token_digest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "raven.db"


@pytest.fixture
async def auth_store(db_path):
    """Build stores for one test and close them whatever the assertions do.

    aiosqlite runs each connection on a non-daemon worker thread, so a store left open by a
    failing assertion keeps the interpreter alive after the report is printed.
    """
    created: list[AuthStore] = []

    def make(path: Path | None = None) -> AuthStore:
        store = AuthStore(path or db_path)
        created.append(store)
        return store

    yield make

    for store in created:
        await store.close()


async def _count(store: AuthStore, table: str) -> int:
    return int((await store._fetchval(f"SELECT COUNT(*) FROM {table}")) or 0)


async def _insert_expired_session(store: AuthStore, suffix: int) -> None:
    """Write an expired row directly, bypassing the issue path so only a sweep can remove it."""
    now = time.time()
    await store._execute(
        "INSERT INTO auth_sessions (token_hash, user_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (f"stale-{suffix}", "user:spin", "user", now - 2, now - 1),
    )
    await store._commit()


async def _insert_live_session(store: AuthStore, user_id: str) -> str:
    token = f"live-{user_id}"
    now = time.time()
    await store._execute(
        "INSERT INTO auth_sessions (token_hash, user_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (_token_digest(token), user_id, "user", now, now + 3600),
    )
    await store._commit()
    return token


async def _account(store: AuthStore, username: str) -> str:
    """A session is only readable while its account row is, so a seeded token needs a real user."""
    await store.create_user(username, "pw")
    return f"user:{username}"


@pytest.mark.asyncio
async def test_expired_sessions_are_dropped_when_the_store_opens(auth_store, db_path):
    seed = auth_store()
    gone = await _account(seed, "gone")
    here = await _account(seed, "here")
    expired = await seed.create_session(gone, "user", ttl_seconds=-1)
    live = await seed.create_session(here, "user", ttl_seconds=3600)
    await seed.close()

    reopened = auth_store(db_path)
    assert await _count(reopened, "auth_sessions") == 1
    assert await reopened.get_session(expired) is None
    assert (await reopened.get_session(live))["user_id"] == "user:here"


@pytest.mark.asyncio
async def test_expired_email_tokens_are_dropped_when_the_store_opens(auth_store):
    seed = auth_store()
    await seed.create_user("alice", "pw", email="alice@example.com")
    unclaimed = await seed.create_email_verification_token("user:alice")
    await seed._execute(
        "UPDATE auth_email_tokens SET expires_at = ? WHERE token_hash = ?",
        (time.time() - 1, _token_digest(unclaimed)),
    )
    await seed._commit()
    assert await _count(seed, "auth_email_tokens") == 1
    await seed.close()

    reopened = auth_store()
    assert await _count(reopened, "auth_email_tokens") == 0


@pytest.mark.asyncio
async def test_the_sweep_leaves_an_unexpired_email_token_spendable(auth_store):
    store = auth_store()
    await store.create_user("bob", "pw", email="bob@example.com")
    token = await store.create_email_verification_token("user:bob")
    assert (await store.purge_expired())["email_tokens"] == 0
    assert await store.verify_email_token(token) is True


@pytest.mark.asyncio
async def test_issuing_a_session_sweeps_so_a_never_restarting_server_stays_bounded(auth_store):
    store = auth_store()
    for i in range(5):
        await _insert_expired_session(store, i)
    spin = await _account(store, "spin")
    live = await store.create_session(spin, "user", ttl_seconds=3600)
    assert await _count(store, "auth_sessions") == 1
    assert (await store.get_session(live))["user_id"] == "user:spin"


@pytest.mark.asyncio
async def test_purge_reports_what_it_removed(auth_store):
    store = auth_store()
    for i in range(3):
        await _insert_expired_session(store, i)
    keep = await _account(store, "keep")
    live = await _insert_live_session(store, keep)
    removed = await store.purge_expired()
    assert removed["sessions"] == 3
    assert removed["email_tokens"] == 0
    assert await _count(store, "auth_sessions") == 1
    assert (await store.get_session(live))["user_id"] == "user:keep"
