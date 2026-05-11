from __future__ import annotations
import pytest
from unittest.mock import AsyncMock
from raven.channels.googlechat.channel import GoogleChatChannel
from raven.core.models import Message, IncomingMessage


@pytest.mark.asyncio
async def test_googlechat_start():
    c = GoogleChatChannel()
    await c.start()
    assert c._ready


@pytest.mark.asyncio
async def test_googlechat_stop():
    c = GoogleChatChannel()
    await c.start()
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_googlechat_handle_webhook():
    handler = AsyncMock()
    c = GoogleChatChannel()
    await c.on_message(handler)
    await c.start()
    body = {"message": {"text": "hi", "sender": {"name": "users/123", "email": "a@b.com"}}, "space": {"name": "spaces/abc"}}
    result = await c.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event = handler.await_args[0][0]
    assert event.channel == "googlechat"
    assert event.text == "hi"


@pytest.mark.asyncio
async def test_googlechat_handle_webhook_no_text():
    handler = AsyncMock()
    c = GoogleChatChannel()
    await c.on_message(handler)
    await c.start()
    result = await c.handle_webhook({"message": {"text": ""}})
    assert not result


@pytest.mark.asyncio
async def test_googlechat_send():
    c = GoogleChatChannel()
    await c.start()
    msg = Message(session_id="g:spc:u", channel="googlechat", role="assistant", content="r")
    await c.send("g:spc:u", msg)
