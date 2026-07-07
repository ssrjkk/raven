from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.telegram.channel import TelegramChannel
from raven.core.models import Message


@pytest.fixture
def channel():
    return TelegramChannel()


@pytest.mark.asyncio
async def test_start_no_token(channel):
    with patch("raven.channels.telegram.channel.settings") as mock_settings:
        mock_settings.telegram_bot_token = ""
        await channel.start()
        assert channel._app is None


@pytest.mark.asyncio
async def test_start_with_token(channel):
    mock_app = MagicMock()
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.stop = AsyncMock()
    mock_app.shutdown = AsyncMock()
    mock_app.updater = MagicMock()
    mock_app.updater.start_polling = AsyncMock()
    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.build.return_value = mock_app
    channel._token = "fake:token"
    with patch("raven.channels.telegram.channel.Application.builder", return_value=mock_builder):
        await channel.start()
        assert channel._app is not None
        await channel.stop()


@pytest.mark.asyncio
async def test_stop(channel):
    mock_app = AsyncMock()
    channel._app = mock_app
    await channel.stop()
    mock_app.stop.assert_awaited_once()
    mock_app.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message(channel):
    handler = AsyncMock()
    await channel.on_message(handler)
    assert channel._handler is handler


@pytest.mark.asyncio
async def test_send_no_app(channel):
    msg = Message(session_id="telegram:C1", channel="telegram", role="assistant", content="hello")
    await channel.send("telegram:C1", msg)


@pytest.mark.asyncio
async def test_send_with_app(channel):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app
    msg = Message(session_id="telegram:12345", channel="telegram", role="assistant", content="hello")
    await channel.send("telegram:12345", msg)
    mock_app.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_invalid_session(channel):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app
    msg = Message(session_id="invalid", channel="telegram", role="assistant", content="hello")
    await channel.send("invalid", msg)
    mock_app.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_typing(channel):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app
    await channel.send_typing(12345)
    mock_app.bot.send_chat_action.assert_awaited_once_with(chat_id=12345, action="typing")


@pytest.mark.asyncio
async def test_send_typing_no_app(channel):
    await channel.send_typing(12345)


@pytest.mark.asyncio
async def test_build_test_app():
    app = TelegramChannel._build_test_app("fake_token")
    assert app is not None


@pytest.mark.asyncio
async def test_channel_id(channel):
    assert channel.channel_id == "telegram"


@pytest.mark.asyncio
async def test_connect_disconnect(channel):
    await channel.connect()
    await channel.disconnect()


@pytest.mark.asyncio
async def test_health_check(channel):
    assert not await channel.health_check()
    channel._ready = True
    assert not await channel.health_check()
    channel._app = AsyncMock()
    assert await channel.health_check()


@pytest.mark.asyncio
async def test_stop_no_app(channel):
    channel._app = None
    await channel.stop()


@pytest.mark.asyncio
async def test_send_menu(channel):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app
    await channel.send_menu(12345, "Pick an option:")
    mock_app.bot.send_message.assert_awaited_once()
    kwargs = mock_app.bot.send_message.await_args[1]
    assert kwargs["chat_id"] == 12345
    assert kwargs["text"] == "Pick an option:"
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_edit_message(channel):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app
    await channel.edit_message(12345, 678, "Updated text")
    mock_app.bot.edit_message_text.assert_awaited_once_with(
        chat_id=12345, message_id=678, text="Updated text", parse_mode="Markdown"
    )


@pytest.mark.asyncio
async def test_send_markdown_fallback(channel):
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = [Exception("Markdown parse error"), None]
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app
    msg = Message(session_id="telegram:12345", channel="telegram", role="assistant", content="*bold*")
    await channel.send("telegram:12345", msg)
    assert mock_bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_send_markdown_fallback_total_failure(channel):
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = [Exception("Markdown error"), Exception("Plain error")]
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app
    msg = Message(session_id="telegram:12345", channel="telegram", role="assistant", content="*bold*")
    await channel.send("telegram:12345", msg)
    assert mock_bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_send_with_show_menu_metadata(channel):
    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app
    msg = Message(
        session_id="telegram:12345", channel="telegram", role="assistant",
        content="Menu time", metadata={"show_menu": True},
    )
    await channel.send("telegram:12345", msg)
    kwargs = mock_bot.send_message.await_args[1]
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_edit_message_fallback(channel):
    mock_bot = AsyncMock()
    mock_bot.edit_message_text.side_effect = [Exception("Markdown error"), None]
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app
    await channel.edit_message(12345, 678, "*bold*")
    assert mock_bot.edit_message_text.await_count == 2


@pytest.mark.asyncio
async def test_edit_message_no_app(channel):
    await channel.edit_message(12345, 678, "text")
