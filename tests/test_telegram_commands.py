from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.telegram.channel import TelegramChannel
from raven.core.models import IncomingMessage, Message


@pytest.fixture
def channel():
    return TelegramChannel()


def _make_update(text: str, chat_id: int = 12345, user_id: int = 100, args: list[str] | None = None):
    update = MagicMock()
    update.message.text = text
    update.message.chat_id = chat_id
    update.effective_chat.id = chat_id
    update.effective_user.id = user_id
    update.effective_user.username = "testuser"
    update.message.from_user.id = user_id
    update.message.from_user.username = "testuser"
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    context = MagicMock()
    context.args = args or []
    return update, context


class TestCmdStart:
    async def test_cmd_start_sends_help(self, channel):
        update, context = _make_update("/start")
        await channel._cmd_start(update, context)
        update.message.reply_text.assert_awaited_once()

    async def test_cmd_start_includes_menu_keyboard(self, channel):
        update, context = _make_update("/start")
        await channel._cmd_start(update, context)
        kwargs = update.message.reply_text.await_args[1]
        assert kwargs.get("reply_markup") is not None


class TestCmdHelp:
    async def test_cmd_help_sends_help(self, channel):
        update, context = _make_update("/help")
        await channel._cmd_help(update, context)
        update.message.reply_text.assert_awaited_once()

    async def test_cmd_help_includes_menu_keyboard(self, channel):
        update, context = _make_update("/help")
        await channel._cmd_help(update, context)
        kwargs = update.message.reply_text.await_args[1]
        assert kwargs.get("reply_markup") is not None


class TestCmdNew:
    async def test_cmd_new_dispatches_incoming(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("/new")
        await channel._cmd_new(update, context)
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert isinstance(event, IncomingMessage)
        assert event.channel == "telegram"
        assert "/new" in event.text

    async def test_cmd_new_generates_unique_session(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update1, ctx1 = _make_update("/new")
        update2, ctx2 = _make_update("/new")
        await channel._cmd_new(update1, ctx1)
        await channel._cmd_new(update2, ctx2)
        event1 = handler.call_args_list[0][0][0]
        event2 = handler.call_args_list[1][0][0]
        assert event1.session_id != event2.session_id


class TestCmdReset:
    async def test_cmd_reset_sends_confirmation(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("/reset")
        await channel._cmd_reset(update, context)
        update.message.reply_text.assert_awaited()
        found = any("reset" in call.args[0].lower() for call in update.message.reply_text.call_args_list)
        assert found

    async def test_cmd_reset_dispatches_incoming(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("/reset")
        await channel._cmd_reset(update, context)
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "/new" in event.text


class TestCmdPair:
    async def test_cmd_pair_with_code(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("/pair abc123", args=["abc123"])
        await channel._cmd_pair(update, context)
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "abc123" in event.text

    async def test_cmd_pair_no_code(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("/pair", args=[])
        await channel._cmd_pair(update, context)
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "/pair" in event.text


class TestCmdMenu:
    async def test_cmd_menu_sends_menu(self, channel):
        mock_app = MagicMock()
        mock_app.bot = AsyncMock()
        channel._app = mock_app
        update, context = _make_update("/menu")
        await channel._cmd_menu(update, context)
        mock_app.bot.send_message.assert_awaited_once()


class TestOnText:
    async def test_on_text_dispatches_handler(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        update, context = _make_update("hello world")
        with patch.object(channel, "send_typing", new_callable=AsyncMock):
            await channel._on_text(update, context)
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert isinstance(event, IncomingMessage)
        assert event.text == "hello world"
        assert event.channel == "telegram"

    async def test_on_text_no_handler(self, channel):
        channel._handler = None
        update, context = _make_update("hello")
        with patch.object(channel, "send_typing", new_callable=AsyncMock):
            await channel._on_text(update, context)


class TestOnVoice:
    async def test_on_voice_processes_audio(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        channel._token = "fake-token"
        voice_file = MagicMock()
        voice_file.file_id = "voice123"
        voice_file.get_file = AsyncMock(return_value=voice_file)
        reply_msg = MagicMock()
        reply_msg.edit_text = AsyncMock()
        update = MagicMock()
        update.message.voice = voice_file
        update.message.chat_id = 12345
        update.effective_chat.id = 12345
        update.effective_user.id = 100
        update.effective_user.username = "testuser"
        update.message.from_user.id = 100
        update.message.from_user.username = "testuser"
        update.message.reply_text = AsyncMock(return_value=reply_msg)
        context = MagicMock()
        with patch.object(channel, "send_typing", new_callable=AsyncMock), patch(
            "raven.channels.telegram.channel.download_voice", new_callable=AsyncMock, return_value="/tmp/audio.ogg"
        ), patch(
            "raven.channels.telegram.channel.transcribe_voice", new_callable=AsyncMock, return_value="transcribed text"
        ):
            await channel._on_voice(update, context)
            handler.assert_awaited_once()
            event = handler.call_args[0][0]
            assert "transcribed" in event.text.lower()


class TestOnCallback:
    async def test_callback_confirm_yes(self, channel):
        event = asyncio.Event()
        channel._confirm_events = {"test123": event}
        query = MagicMock()
        query.data = "cy:test123"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.message = MagicMock()
        update.message.chat_id = 12345
        context = MagicMock()
        await channel._on_callback(update, context)
        assert event.is_set()
        query.answer.assert_awaited()

    async def test_callback_confirm_no(self, channel):
        event = asyncio.Event()
        channel._confirm_events = {"test123": event}
        query = MagicMock()
        query.data = "cn:test123"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.message = MagicMock()
        update.message.chat_id = 12345
        context = MagicMock()
        await channel._on_callback(update, context)
        assert channel._confirm_results.get("test123") is False
        query.answer.assert_awaited()

    async def test_callback_menu_button(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        query = MagicMock()
        query.data = "menu_new"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.answer = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.message = MagicMock()
        update.message.chat_id = 12345
        context = MagicMock()
        with patch("asyncio.wait_for", new_callable=AsyncMock, return_value=True):
            await channel._on_callback(update, context)
        handler.assert_awaited_once()
