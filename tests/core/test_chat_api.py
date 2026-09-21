from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.chat_api import create_chat_router, set_database


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(create_chat_router())
    return TestClient(app)


def test_search_chat_no_db(client: TestClient) -> None:
    set_database(None)
    resp = client.get("/api/chat/search", params={"q": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["total"] == 0


def test_search_chat_with_results(client: TestClient) -> None:
    rows = [
        {"id": "1", "session_id": "s1", "role": "user", "content": "hello world", "created_at": "2026-01-01", "session_name": "test"},
        {"id": "2", "session_id": "s1", "role": "assistant", "content": "hello there", "created_at": "2026-01-02", "session_name": "test"},
    ]

    cursor = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=cursor)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    db_conn = MagicMock()
    db_conn.execute = MagicMock(return_value=conn_ctx)

    mock_db = MagicMock()
    mock_db.conn = db_conn

    set_database(mock_db)
    resp = client.get("/api/chat/search", params={"q": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["results"][0]["role"] == "user"


def test_search_chat_error_handling(client: TestClient) -> None:
    db_conn = MagicMock()
    db_conn.execute = MagicMock(side_effect=RuntimeError("db down"))

    mock_db = MagicMock()
    mock_db.conn = db_conn

    set_database(mock_db)
    resp = client.get("/api/chat/search", params={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert "error" in data
