from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.whatsapp.channel import WhatsAppChannel
from raven.core.models import IncomingMessage, Message


@pytest.mark.asyncio
async def test_whatsapp_start():
    channel = WhatsAppChannel()
    await channel.start()
    assert channel._ready


@pytest.mark.asyncio
async def test_whatsapp_stop():
    channel = WhatsAppChannel()
    await channel.start()
    await channel.stop()
    assert not channel._ready


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_no_handler():
    channel = WhatsAppChannel()
    await channel.start()
    result = await channel.handle_webhook({"entry": []})
    assert not result


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_text():
    handler = AsyncMock()
    channel = WhatsAppChannel()
    await channel.on_message(handler)
    await channel.start()
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "12345",
                                    "id": "msg1",
                                    "type": "text",
                                    "text": {"body": "Hello WhatsApp"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    result = await channel.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event: IncomingMessage = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "whatsapp"
    assert event.user_id == "12345"
    assert event.text == "Hello WhatsApp"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_no_text():
    handler = AsyncMock()
    channel = WhatsAppChannel()
    await channel.on_message(handler)
    await channel.start()
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "12345",
                                    "id": "msg2",
                                    "type": "image",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    result = await channel.handle_webhook(body)
    assert not result
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_send():
    channel = WhatsAppChannel()
    await channel.start()
    msg = Message(session_id="whatsapp:12345", channel="whatsapp", role="assistant", content="reply")
    await channel.send("whatsapp:12345", msg)
