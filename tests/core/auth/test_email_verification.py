"""A verification credential must be spendable only by whoever received it.

Three defects are pinned here: the credential used to be stored as itself, used to be written to
the log, and used to arrive in a query string. It now lives as a digest, travels by email, and is
spent through a POST.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from raven.core.auth.store import AuthStore
from raven.core.migrations import apply_pending_migrations

_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{40,}")


@pytest.fixture
async def store(tmp_path: Path):
    s = AuthStore(tmp_path / "auth.db")
    yield s
    await s.close()


@contextlib.contextmanager
def log_sink(sink: list[str]) -> Iterator[None]:
    handler = logger.add(sink.append, level="DEBUG", format="{message}")
    try:
        yield
    finally:
        logger.remove(handler)


def read_table(db_path: Path, table: str) -> tuple[list[str], list[tuple[object, ...]]]:
    con = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
        rows = list(con.execute(f"SELECT * FROM {table}"))
        return columns, rows
    finally:
        con.close()


def make_client(db_path: Path) -> TestClient:
    from raven.core.admin_api import init_auth_routes

    app = FastAPI()
    init_auth_routes(app, str(db_path))
    return TestClient(app)


def patch_transport(monkeypatch: pytest.MonkeyPatch, captured: dict[str, str], result: str) -> None:
    import raven.tools.email as email_tool

    async def fake_send(to: str, subject: str, body: str) -> str:
        captured["to"] = to
        captured["body"] = body
        return result

    monkeypatch.setattr(email_tool, "email_send", fake_send)


@pytest.mark.asyncio
async def test_the_row_holds_a_digest_and_never_the_credential(store: AuthStore, tmp_path: Path) -> None:
    user = await store.create_user("alice", "Secret123!", email="alice@example.com")
    token = await store.create_email_verification_token(user.id)

    columns, rows = read_table(tmp_path / "auth.db", "auth_email_tokens")
    values = {str(value) for row in rows for value in row}
    assert "token" not in columns
    assert "token_hash" in columns
    assert rows
    assert token not in values
    assert hashlib.sha256(token.encode("utf-8")).hexdigest() in values


@pytest.mark.asyncio
async def test_verification_confirms_the_address_once(store: AuthStore) -> None:
    user = await store.create_user("bob", "Secret123!", email="bob@example.com")
    token = await store.create_email_verification_token(user.id)

    assert await store.verify_email_token(token) is True
    updated = await store.get_user("bob")
    assert updated is not None and updated.email_verified is True
    assert await store.verify_email_token(token) is False, "a spent credential spent again"


@pytest.mark.asyncio
async def test_an_unknown_or_expired_credential_verifies_nothing(store: AuthStore) -> None:
    user = await store.create_user("carol", "Secret123!", email="carol@example.com")
    token = await store.create_email_verification_token(user.id)

    assert await store.verify_email_token("not-a-token") is False

    db = await store._conn()
    await db.execute("UPDATE auth_email_tokens SET expires_at = ? WHERE user_id = ?", (1.0, user.id))
    await db.commit()

    assert await store.verify_email_token(token) is False
    assert await store.has_pending_email_verification(user.id) is False


@pytest.mark.asyncio
async def test_the_migration_revokes_rows_that_were_stored_as_credentials(store: AuthStore) -> None:
    user = await store.create_user("dave", "Secret123!", email="dave@example.com")
    token = await store.create_email_verification_token(user.id)

    db = await store._conn()
    await db.run_script("ALTER TABLE auth_email_tokens RENAME COLUMN token_hash TO token")
    await db.execute("DELETE FROM _migrations WHERE version = 11")
    await db.commit()

    await apply_pending_migrations(db)

    assert await store.verify_email_token(token) is False
    _, rows = read_table(Path(store.db_path), "auth_email_tokens")
    assert rows == []


@pytest.mark.asyncio
async def test_the_credential_reaches_the_address_and_no_log_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path / "auth_api.db")
    captured: dict[str, str] = {}
    patch_transport(monkeypatch, captured, "sent")

    logs: list[str] = []
    with log_sink(logs):
        response = client.post(
            "/api/auth/register", json={"username": "erin", "password": "Secret123!", "email": "erin@example.com"}
        )
    assert response.status_code == 200
    token = captured["body"].strip().splitlines()[-1]
    assert captured["to"] == "erin@example.com"
    assert token and not any(token in line for line in logs), "the credential was logged"


@pytest.mark.asyncio
async def test_a_missing_transport_is_reported_without_leaking_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path / "auth_api.db")
    captured: dict[str, str] = {}
    patch_transport(monkeypatch, captured, "[error] SMTP not configured")

    logs: list[str] = []
    with log_sink(logs):
        response = client.post(
            "/api/auth/register", json={"username": "frank", "password": "Secret123!", "email": "frank@example.com"}
        )
    assert response.status_code == 200
    warnings = [line for line in logs if "stays pending" in line]
    assert any("SMTP not configured" in line for line in warnings)
    assert any("frank@example.com" in line for line in warnings)
    assert not [line for line in logs if _TOKEN_SHAPE.search(line)], "a credential-shaped string was logged"


def test_verification_is_a_post_and_a_get_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path / "auth_api.db")
    captured: dict[str, str] = {}
    patch_transport(monkeypatch, captured, "sent")

    client.post("/api/auth/register", json={"username": "grace", "password": "Secret123!", "email": "g@example.com"})
    token = captured["body"].strip().splitlines()[-1]

    assert client.get("/api/auth/verify-email", params={"token": token}).status_code == 405
    assert client.post("/api/auth/verify-email", json={"token": "wrong"}).status_code == 400
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200


def test_the_credential_does_not_appear_in_a_request_repr() -> None:
    from pydantic import SecretStr

    from raven.core.admin.models import AuthVerifyEmailRequest

    request = AuthVerifyEmailRequest(token=SecretStr("super-secret-value-that-is-long"))
    assert "super-secret-value-that-is-long" not in repr(request)
    assert "super-secret-value-that-is-long" not in str(request)
