from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from raven.core.webhooks import create_webhook_router
from raven.core.models import IncomingMessage


class FakeAppState:
    pass


class FakeRequest:
    def __init__(self, headers=None, app_state=None):
        self.headers = headers or {}
        self.app = MagicMock()
        self.app.state = app_state or FakeAppState()
        self.query_params = {}


class FakeDB:
    async def health_check(self):
        return True


@pytest.mark.asyncio
async def test_generic_webhook_text_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    body = {"text": "hello"}
    req = FakeRequest(headers={"X-Webhook-Source": "github"})
    resp = await router.routes[0].endpoint(body, req)
    assert resp["ok"] is True
    handler.assert_awaited_once()
    event = handler.await_args[0][0]
    assert event.channel == "webhook"
    assert event.text == "hello"


@pytest.mark.asyncio
async def test_generic_webhook_message_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    body = {"message": "world"}
    req = FakeRequest(headers={"X-Webhook-Source": "test"})
    resp = await router.routes[0].endpoint(body, req)
    assert resp["ok"] is True
    event = handler.await_args[0][0]
    assert event.text == "world"


@pytest.mark.asyncio
async def test_generic_webhook_no_text():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    body = {"not_text": ""}
    req = FakeRequest()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await router.routes[0].endpoint(body, req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_slack_url_verification():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    body = {"type": "url_verification", "challenge": "abc123"}
    req = FakeRequest()
    resp = await router.routes[1].endpoint(body, req)
    assert resp == {"challenge": "abc123"}


@pytest.mark.asyncio
async def test_slack_events_no_channel():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    body = {"type": "event_callback", "event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1"}}
    req = FakeRequest()
    resp = await router.routes[1].endpoint(body, req)
    assert resp["ok"] is True


@pytest.mark.asyncio
async def test_whatsapp_verify():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)
    req = FakeRequest()
    req.query_params = {"hub.mode": "subscribe", "hub.verify_token": "wrong_token", "hub.challenge": "123"}
    with pytest.raises(Exception):
        await router.routes[3].endpoint(req)
