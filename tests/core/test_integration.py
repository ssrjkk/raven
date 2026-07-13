from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from raven.core.config import get_settings
from raven.core.db import Database
from raven.core.webhooks import create_webhook_router


@pytest.fixture
def db():
    from pathlib import Path
    return Database(Path(":memory:"))


@pytest.fixture
def app(db):
    s = get_settings()
    s.web_secret_key = "test-secret-key"
    api = FastAPI()
    api.state.slack_channel = None
    api.state.whatsapp_channel = None
    api.state.googlechat_channel = None
    api.state.signal_channel = None
    api.state.teams_channel = None
    api.state.feishu_channel = None
    api.state.line_channel = None
    async def handle_incoming(event):
        pass
    router = create_webhook_router(db, handle_incoming)
    api.include_router(router)
    return api


@pytest.fixture(autouse=True)
def _patch_webhook_settings():
    from unittest.mock import patch
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = "test-secret-key"
        yield


@pytest.mark.asyncio
async def test_webhook_generic(app):
    transport = ASGITransport(app=app)
    import hashlib
    import hmac as hmac_mod
    body_bytes = b'{"text":"hello world"}'
    sig = "sha256=" + hmac_mod.new(b"test-secret-key", body_bytes, hashlib.sha256).hexdigest()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/generic",
            content=body_bytes,
            headers={
                "X-Webhook-Source": "test",
                "X-Webhook-Signature": sig,
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "test"


@pytest.mark.asyncio
async def test_webhook_github_actions_skipped(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/github-actions",
            json={"action": "in_progress", "workflow_run": {}},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped"] is True


@pytest.mark.asyncio
async def test_webhook_github_actions_failure(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/github-actions",
            json={
                "action": "completed",
                "workflow_run": {
                    "name": "CI Pipeline",
                    "conclusion": "failure",
                    "head_branch": "main",
                    "head_commit": {"id": "abc123"},
                },
                "repository": {"full_name": "test/test", "name": "test"},
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_webhook_allure_missing_path(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/allure",
            json={},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_allure(app, tmp_path):
    results_dir = tmp_path / "allure-results"
    results_dir.mkdir()
    (results_dir / "test-result.json").write_text(
        '{"name": "test_login", "status": "failed", "statusDetails": {"message": "Timeout waiting for element"},"labels": [{"name": "testMethod", "value": "test_login.py"}],"attachments": []}'
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/allure",
            json={"results_path": str(results_dir)},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
