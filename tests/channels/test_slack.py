from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from raven.channels.slack.channel import SlackChannel
from raven.core.models import Message, IncomingMessage


@pytest.mark.asyncio
async def test_slack_start_no_token():
    channel = SlackChannel()
    channel._token = ""
    await channel.start()
    assert not channel._ready


@pytest.mark.asyncio
async def test_slack_start_no_sdk():
    with patch("raven.channels.slack.channel.HAS_SLACK", False):
        channel = SlackChannel()
        channel._token = "xoxb-test"
        await channel.start()
        assert not channel._ready


@pytest.mark.asyncio
async def test_slack_start_with_token():
    channel = SlackChannel()
    channel._token = "xoxb-test"
    with patch("raven.channels.slack.channel.HAS_SLACK", True), \
         patch("raven.channels.slack.channel._SlackClient") as mock_cls:
        await channel.start()
    assert channel._ready
    mock_cls.assert_called_once_with(token="xoxb-test")


@pytest.mark.asyncio
async def test_slack_stop():
    channel = SlackChannel()
    channel._ready = True
    await channel.stop()
    assert not channel._ready


@pytest.mark.asyncio
async def test_slack_handle_event_bot_message():
    handler = AsyncMock()
    channel = SlackChannel()
    await channel.on_message(handler)
    await channel.handle_event({"type": "message", "subtype": "bot_message", "user": "U1", "text": "hi", "channel": "C1"})
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_handle_event_message():
    handler = AsyncMock()
    channel = SlackChannel()
    await channel.on_message(handler)
    await channel.handle_event({"type": "message", "user": "U1", "text": "hello", "channel": "C1", "ts": "123.456"})
    handler.assert_awaited_once()
    event: IncomingMessage = handler.await_args[0][0]
    assert event.channel == "slack"
    assert event.user_id == "U1"
    assert event.text == "hello"


@pytest.mark.asyncio
async def test_slack_handle_event_no_handler():
    channel = SlackChannel()
    result = await channel.handle_event({"type": "message", "user": "U1", "text": "hi", "channel": "C1"})
    assert result is None


@pytest.mark.asyncio
async def test_slack_send_not_ready():
    channel = SlackChannel()
    msg = Message(session_id="slack:C1:U1", channel="slack", role="assistant", content="reply")
    await channel.send("slack:C1:U1", msg)


@pytest.mark.asyncio
async def test_slack_send_with_client():
    channel = SlackChannel()
    channel._client = AsyncMock()
    channel._ready = True
    msg = Message(session_id="slack:C1", channel="slack", role="assistant", content="reply")
    await channel.send("slack:C1", msg)
    channel._client.chat_postMessage.assert_awaited_once_with(channel="C1", text="reply")


@pytest.mark.asyncio
async def test_slack_send_thread():
    channel = SlackChannel()
    channel._client = AsyncMock()
    channel._ready = True
    msg = Message(session_id="slack:C1:123.456", channel="slack", role="assistant", content="reply")
    await channel.send("slack:C1:123.456", msg)
    channel._client.chat_postMessage.assert_awaited_once_with(channel="C1", text="reply", thread_ts="123.456")


@pytest.mark.asyncio
async def test_slack_send_bad_session():
    channel = SlackChannel()
    channel._client = AsyncMock()
    channel._ready = True
    msg = Message(session_id="invalid", channel="slack", role="assistant", content="reply")
    await channel.send("invalid", msg)
    channel._client.chat_postMessage.assert_not_awaited()
