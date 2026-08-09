from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.middleware import request_id_middleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_id_middleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "pong"}

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
