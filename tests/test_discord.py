from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import raven.channels.discord.channel as discord_channel_mod
from raven.channels.discord.channel import COLORS, DiscordChannel
from raven.core.models import Message


@pytest.fixture
def channel():
    return DiscordChannel()


def _fake_discord(bot: MagicMock) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """The three library names the channel module binds at import time, faked.

    discord.py is an optional extra and CI installs `.[dev]` only, so patching
    `raven.channels.discord.channel.discord` raises AttributeError there and the lifecycle below would
    only ever be asserted on a machine that happens to have the package. Injecting the names instead
    keeps the assertion runner-independent.
    """
    intents = MagicMock()
    intents.default.return_value = intents
    return (
        SimpleNamespace(Intents=intents, Embed=MagicMock(), Game=MagicMock(), DMChannel=MagicMock()),
        SimpleNamespace(Bot=MagicMock(return_value=bot)),
        SimpleNamespace(CommandTree=MagicMock(), describe=MagicMock()),
    )


def _install_discord(monkeypatch: pytest.MonkeyPatch, bot: MagicMock) -> None:
    fake_discord, fake_commands, fake_app_commands = _fake_discord(bot)
    monkeypatch.setattr(discord_channel_mod, "HAS_DISCORD", True)
    monkeypatch.setattr(discord_channel_mod, "discord", fake_discord, raising=False)
    monkeypatch.setattr(discord_channel_mod, "commands", fake_commands, raising=False)
    monkeypatch.setattr(discord_channel_mod, "app_commands", fake_app_commands, raising=False)


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
async def test_start_with_deps(channel, monkeypatch: pytest.MonkeyPatch):
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock(return_value=None)
    _install_discord(monkeypatch, mock_bot)
    channel._token = "fake_token"
    await channel.start()
    assert channel._bot is mock_bot


@pytest.mark.asyncio
async def test_stop(channel):
    mock_bot = AsyncMock()
    channel._bot = mock_bot
    await channel.stop()
    mock_bot.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_disconnect(channel, monkeypatch: pytest.MonkeyPatch):
    """`connect` reaches `start`, which launches the gateway client in a task. Unmocked, a machine
    that carries DISCORD_BOT_TOKEN gets a live connection attempt and a task nobody cancels."""
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    _install_discord(monkeypatch, mock_bot)
    channel._token = "fake_token"
    await channel.connect()
    await asyncio.sleep(0)
    mock_bot.start.assert_awaited_once_with("fake_token")
    await channel.disconnect()
    mock_bot.close.assert_awaited_once()


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


def test_build_embed(monkeypatch: pytest.MonkeyPatch):
    """What matters here are the four platform caps (256 / 4096 / 256 / 1024) and the color map, so the
    library is injected rather than required — with `.[dev]` alone CI never executed this code."""
    embed = MagicMock()
    fake_discord = SimpleNamespace(Embed=MagicMock(return_value=embed))
    monkeypatch.setattr(discord_channel_mod, "discord", fake_discord, raising=False)

    built = discord_channel_mod.build_embed("t" * 300, "d" * 5000, "no-such-color", [("k" * 300, "v" * 2000, True)])

    assert built is embed
    _args, kwargs = fake_discord.Embed.call_args
    assert kwargs["title"] == "t" * 256
    assert kwargs["description"] == "d" * 4096
    assert kwargs["color"] == COLORS["info"]
    embed.add_field.assert_called_once_with(name="k" * 256, value="v" * 1024, inline=True)


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
async def test_send_with_embed(channel, monkeypatch: pytest.MonkeyPatch):
    embed = MagicMock()
    fake_discord = SimpleNamespace(Embed=MagicMock(return_value=embed))
    monkeypatch.setattr(discord_channel_mod, "discord", fake_discord, raising=False)
    mock_ch = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_ch
    channel._bot = mock_bot
    channel._ready = True
    msg = Message(
        session_id="discord:12345:default",
        channel="discord",
        role="assistant",
        content="Embed content",
        metadata={"as_embed": True, "embed_title": "Title", "embed_color": "success"},
    )
    await channel.send("discord:12345:default", msg)
    _args, kwargs = mock_ch.send.await_args
    assert kwargs["embed"] is embed
    _inner_args, inner_kwargs = fake_discord.Embed.call_args
    assert inner_kwargs["title"] == "Title"
    assert inner_kwargs["color"] == COLORS["success"]


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
