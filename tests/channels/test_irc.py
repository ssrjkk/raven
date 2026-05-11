from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from raven.channels.irc.channel import IRCChannel
from raven.core.models import Message, IncomingMessage


@pytest.mark.asyncio
async def test_irc_start_no_sdk():
    with patch("raven.channels.irc.channel.HAS_IRC", False):
        c = IRCChannel()
        await c.start()
        assert not c._ready


@pytest.mark.asyncio
async def test_irc_start():
    with patch("raven.channels.irc.channel.HAS_IRC", True):
        c = IRCChannel()
        await c.start()
        assert c._ready


@pytest.mark.asyncio
async def test_irc_stop():
    c = IRCChannel()
    c._ready = True
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_irc_handle_message():
    handler = AsyncMock()
    c = IRCChannel()
    await c.on_message(handler)
    c._ready = True
    await c.handle_message("user1", "#raven", "hello")
    handler.assert_awaited_once()
    event = handler.await_args[0][0]
    assert event.channel == "irc"
    assert event.user_id == "user1"
    assert event.text == "hello"


@pytest.mark.asyncio
async def test_irc_handle_self_message():
    handler = AsyncMock()
    c = IRCChannel()
    c._nick = "raven-bot"
    await c.on_message(handler)
    c._ready = True
    await c.handle_message("raven-bot", "#raven", "hello")
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_irc_send():
    c = IRCChannel()
    c._ready = True
    msg = Message(session_id="irc:#ch:u", channel="irc", role="assistant", content="r")
    await c.send("irc:#ch:u", msg)
