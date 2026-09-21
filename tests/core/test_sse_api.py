from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.sse_api import create_sse_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(create_sse_router())
    return TestClient(app)


def test_events_sessions_no_auth(client: TestClient) -> None:
    resp = client.get("/events/sessions")
    assert resp.status_code == 401


def test_events_sessions_invalid_token(client: TestClient) -> None:
    with patch("raven.core.sse_api.token_manager") as mock_tm, patch("raven.core.sse_api.settings") as mock_settings:
        mock_tm.validate_token.return_value = None
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = ""
        mock_settings.web_secret_key = mock_secret
        resp = client.get("/events/sessions", params={"token": "bad-token"})
        assert resp.status_code == 401


def test_events_sessions_valid_token(client: TestClient) -> None:
    with patch("raven.core.sse_api.token_manager") as mock_tm, patch("raven.core.sse_api.sse_stream") as mock_stream:
        mock_tm.validate_token.return_value = {"user_id": "test-user"}

        async def empty_gen():
            return
            yield

        mock_stream.stream.return_value = empty_gen()
        resp = client.get("/events/sessions", params={"token": "valid-token"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"


def test_events_sessions_web_secret(client: TestClient) -> None:
    with patch("raven.core.sse_api.token_manager") as mock_tm, patch("raven.core.sse_api.settings") as mock_settings, patch("raven.core.sse_api.sse_stream") as mock_stream:
        mock_tm.validate_token.return_value = None
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "admin-secret"
        mock_settings.web_secret_key = mock_secret

        async def empty_gen():
            return
            yield

        mock_stream.stream.return_value = empty_gen()
        resp = client.get("/events/sessions", params={"token": "admin-secret"})
        assert resp.status_code == 200
