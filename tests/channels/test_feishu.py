from __future__ import annotations
import pytest
from unittest.mock import AsyncMock
from raven.channels.feishu.channel import FeishuChannel
from raven.core.models import Message, IncomingMessage


@pytest.mark.asyncio
async def test_feishu_start():
    c = FeishuChannel()
    await c.start()
    assert c._ready


@pytest.mark.asyncio
async def test_feishu_stop():
    c = FeishuChannel()
    c._ready = True
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_feishu_handle_webhook():
    handler = AsyncMock()
    c = FeishuChannel()
    await c.on_message(handler)
    await c.start()
    body = {
        "header": {"event_id": "evt1"},
        "event": {
            "sender": {"sender_id": {"user_id": "u1"}},
            "message": {"content": '{"text":"hello feishu"}'},
        },
    }
    result = await c.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event = handler.await_args[0][0]
    assert event.channel == "feishu"
    assert event.text == "hello feishu"


@pytest.mark.asyncio
async def test_feishu_handle_webhook_no_text():
    handler = AsyncMock()
    c = FeishuChannel()
    await c.on_message(handler)
    await c.start()
    result = await c.handle_webhook({})
    assert not result


@pytest.mark.asyncio
async def test_feishu_send():
    c = FeishuChannel()
    await c.start()
    msg = Message(session_id="f:u", channel="feishu", role="assistant", content="r")
    await c.send("f:u", msg)
