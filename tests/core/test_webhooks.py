from __future__ import annotations

import json as json_mod
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.webhooks import create_webhook_router


class FakeAppState:
    pass


class FakeRequest:
    def __init__(self, headers=None, app_state=None, body_bytes=None):
        self.headers = headers or {}
        self.app = MagicMock()
        self.app.state = app_state or FakeAppState()
        self.query_params = {}
        self._body_bytes = body_bytes or b"{}"

    async def body(self):
        return self._body_bytes


class FakeDB:
    async def health_check(self):
        return True


@pytest.mark.asyncio
async def test_generic_webhook_text_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"text": "hello"}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib, hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Source": "github", "X-Webhook-Signature": sig}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = "test-secret"
        resp = await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True
    handler.assert_awaited_once()
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "webhook"
    assert "hello" in event.text
    assert "<<<EXTERNAL_UNTRUSTED_CONTENT>>>" in event.text


@pytest.mark.asyncio
async def test_generic_webhook_message_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"message": "world"}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib, hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Source": "test", "X-Webhook-Signature": sig}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = "test-secret"
        resp = await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True
    event = handler.await_args[0][0]  # type: ignore[index]
    assert "world" in event.text
    assert "<<<EXTERNAL_UNTRUSTED_CONTENT>>>" in event.text


@pytest.mark.asyncio
async def test_generic_webhook_no_text():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"not_text": ""}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib, hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Signature": sig}, body_bytes=body_bytes)
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = "test-secret"
        with pytest.raises(HTTPException) as exc:
            await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_slack_url_verification():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "url_verification", "challenge": "abc123"}
    req = FakeRequest()
    resp = await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp == {"challenge": "abc123"}


@pytest.mark.asyncio
async def test_slack_events_no_channel():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "event_callback", "event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1"}}
    req = FakeRequest()
    resp = await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True


@pytest.mark.asyncio
async def test_whatsapp_verify():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    req = FakeRequest()
    req.query_params = {"hub.mode": "subscribe", "hub.verify_token": "wrong_token", "hub.challenge": "123"}
    with pytest.raises(Exception):
        await router.routes[3].endpoint(req)  # type: ignore[attr-defined]
