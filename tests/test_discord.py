from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.discord.channel import DiscordChannel, HAS_DISCORD
from raven.core.models import Message


@pytest.fixture
def channel():
    return DiscordChannel()


@pytest.mark.asyncio
async def test_start_no_discord(channel):
    with patch("raven.channels.discord.channel.HAS_DISCORD", False):
        await channel.start()
        assert not channel._ready


@pytest.mark.asyncio
async def test_start_no_token(channel):
    with patch("raven.channels.discord.channel.HAS_DISCORD", True):
        with patch.object(channel, "_token", None):
            await channel.start()
            assert not channel._ready


@pytest.mark.asyncio
async def test_start_with_deps(channel):
    if HAS_DISCORD:
        with patch("raven.channels.discord.channel.discord.Intents.default"):
            with patch("raven.channels.discord.channel.discord.Intents"):
                with patch("raven.channels.discord.channel.commands.Bot") as MockBot:
                    mock_bot = MagicMock()
                    mock_bot.start = AsyncMock(return_value=None)
                    MockBot.return_value = mock_bot
                    with patch("raven.channels.discord.channel.app_commands.CommandTree"):
                        channel._token = "fake_token"
                        await channel.start()
        assert channel._bot is not None


@pytest.mark.asyncio
async def test_stop(channel):
    mock_bot = AsyncMock()
    channel._bot = mock_bot
    await channel.stop()
    mock_bot.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_disconnect(channel):
    await channel.connect()
    await channel.disconnect()


@pytest.mark.asyncio
async def test_on_message(channel):
    handler = AsyncMock()
    await channel.on_message(handler)
    assert channel._handler is handler


@pytest.mark.asyncio
async def test_send_not_ready(channel):
    msg = Message(session_id="discord:C1", channel="discord", role="assistant", content="hello")
    await channel.send("discord:C1", msg)


@pytest.mark.asyncio
async def test_send_no_bot(channel):
    channel._ready = True
    msg = Message(session_id="discord:12345", channel="discord", role="assistant", content="hello")
    await channel.send("discord:12345", msg)


@pytest.mark.asyncio
async def test_send_invalid_session(channel):
    mock_channel = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_channel
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(session_id="discord:invalid", channel="discord", role="assistant", content="hello")
    await channel.send("discord:invalid", msg)


@pytest.mark.asyncio
async def test_channel_id(channel):
    assert channel.channel_id == "discord"


@pytest.mark.asyncio
async def test_build_embed():
    if HAS_DISCORD:
        from raven.channels.discord.channel import build_embed

        embed = build_embed("Test", "Description", "info", [("Key", "Value", True)])
        assert embed is not None
