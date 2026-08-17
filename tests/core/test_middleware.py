from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.auth.tokens import token_manager
from raven.core.middleware import auth_middleware, request_id_middleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_id_middleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "pong"}

    return app


def _make_full_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_middleware)

    @app.post("/api/echo")
    async def echo() -> dict[str, str]:
        return {"ok": "echo"}

    @app.get("/api/read")
    async def read() -> dict[str, str]:
        return {"ok": "read"}

    @app.post("/api/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    @app.post("/api/webhooks/generic")
    async def webhook() -> dict[str, str]:
        return {"ok": "webhook"}

    return app


def test_generates_correlation_id_on_response() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    cid = resp.headers.get("X-Correlation-ID")
    assert cid is not None
    assert len(cid) == 32


def test_passthrough_existing_correlation_id() -> None:
    client = TestClient(_make_app())
    cid = uuid.uuid4().hex
    resp = client.get("/ping", headers={"X-Correlation-ID": cid})
    assert resp.status_code == 200
    assert resp.headers.get("X-Correlation-ID") == cid


class TestApiMutationGuard:
    def test_anonymous_mutation_rejected(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/echo").status_code == 401
        assert client.put("/api/echo").status_code == 401
        assert client.delete("/api/echo").status_code == 401

    def test_anonymous_read_allowed(self) -> None:
        client = TestClient(_make_full_app())
        assert client.get("/api/read").status_code == 200

    def test_bearer_token_allowed(self) -> None:
        token = token_manager.create_token("u1", "user")
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_raven_key_allowed(self) -> None:
        from raven.core.config import settings

        key = settings.web_secret_key.get_secret_value()
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"X-Raven-Key": key})
        assert resp.status_code == 200

    def test_invalid_token_rejected(self) -> None:
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"Authorization": "Bearer bogus-token"})
        assert resp.status_code == 401

    def test_auth_login_public(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/auth/login").status_code == 200

    def test_webhooks_public(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/webhooks/generic").status_code == 200

    @pytest.mark.asyncio
    async def test_garbage_body_still_blocked_before_parse(self) -> None:
        # mutation guard runs before body parsing — even invalid JSON is rejected unauthenticated
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", content=b"{not json", headers={"content-type": "application/json"})
        assert resp.status_code == 401
