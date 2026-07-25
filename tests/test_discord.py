from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.discord.channel import HAS_DISCORD, DiscordChannel
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
    with patch("raven.channels.discord.channel.HAS_DISCORD", True), patch.object(channel, "_token", None):
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


@pytest.mark.asyncio
async def test_health_check(channel):
    assert not await channel.health_check()
    channel._ready = True
    assert not await channel.health_check()
    channel._bot = AsyncMock()
    assert await channel.health_check()


@pytest.mark.asyncio
async def test_stop_no_bot(channel):
    channel._bot = None
    await channel.stop()


@pytest.mark.asyncio
async def test_send_with_channel(channel):
    mock_ch = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_ch
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(session_id="discord:12345:default", channel="discord", role="assistant", content="Hello")
    await channel.send("discord:12345:default", msg)
    mock_bot.get_channel.assert_called_once_with(12345)
    mock_ch.send.assert_awaited_once_with("Hello")


@pytest.mark.asyncio
async def test_send_with_embed(channel):
    if not HAS_DISCORD:
        pytest.skip("discord.py not installed")
    import discord

    from raven.channels.discord.channel import build_embed

    mock_ch = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_ch
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(
        session_id="discord:12345:default", channel="discord", role="assistant",
        content="Embed content", metadata={"as_embed": True, "embed_title": "Title", "embed_color": "success"},
    )
    await channel.send("discord:12345:default", msg)
    mock_ch.send.assert_awaited_once()
    _args, kwargs = mock_ch.send.await_args
    assert "embed" in kwargs
    assert isinstance(kwargs["embed"], discord.Embed)


@pytest.mark.asyncio
async def test_send_long_content(channel):
    mock_ch = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_ch
    channel._bot = mock_bot
    channel._ready = True
    long_text = "x" * 5000
    msg = Message(session_id="discord:12345:default", channel="discord", role="assistant", content=long_text)
    await channel.send("discord:12345:default", msg)
    args, kwargs = mock_ch.send.await_args
    text = kwargs.get("text", args[0] if args else "")
    assert len(text) == 1903
    assert text.endswith("...")


@pytest.mark.asyncio
async def test_send_dm(channel):
    mock_user = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = None
    mock_bot.fetch_user = AsyncMock(return_value=mock_user)
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(session_id="discord:dm_999:default", channel="discord", role="assistant", content="DM reply")
    await channel.send("discord:dm_999:default", msg)
    mock_bot.fetch_user.assert_awaited_once_with(999)
    mock_user.send.assert_awaited_once_with("DM reply")


@pytest.mark.asyncio
async def test_send_channel_not_found(channel):
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = None
    mock_bot.fetch_user = AsyncMock(return_value=None)
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(session_id="discord:99999:default", channel="discord", role="assistant", content="nowhere")
    await channel.send("discord:99999:default", msg)
    mock_bot.get_channel.assert_called_once_with(99999)
    mock_bot.fetch_user.assert_awaited_once_with(99999)


@pytest.mark.asyncio
async def test_send_fetch_user_failure(channel):
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = None
    mock_bot.fetch_user = AsyncMock(side_effect=Exception("API error"))
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(session_id="discord:dm_999:default", channel="discord", role="assistant", content="fail")
    await channel.send("discord:dm_999:default", msg)


@pytest.mark.asyncio
async def test_disconnect(channel):
    mock_bot = AsyncMock()
    channel._bot = mock_bot
    await channel.disconnect()
    mock_bot.close.assert_awaited_once()
