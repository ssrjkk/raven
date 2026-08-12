from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import telegram

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import notify as notify_tools


class TestNotifyTelegram:
    async def test_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = await notify_tools.notify_telegram("hi")
        assert result == "Telegram not configured (no bot token)"

    async def test_token_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:token")
        fake_bot = MagicMock()
        fake_bot.send_message = AsyncMock(return_value=None)
        monkeypatch.setattr(telegram, "Bot", MagicMock(return_value=fake_bot))
        result = await notify_tools.notify_telegram("x" * 4500, chat_id="42")
        assert result == "Sent Telegram notification"
        fake_bot.send_message.assert_awaited_once_with(chat_id="42", text="x" * 4000)

    async def test_explicit_token_no_chat_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_bot = MagicMock()
        fake_bot.send_message = AsyncMock(return_value=None)
        monkeypatch.setattr(telegram, "Bot", MagicMock(return_value=fake_bot))
        result = await notify_tools.notify_telegram("hi", token="token")
        assert result == "Sent Telegram notification"
        fake_bot.send_message.assert_not_awaited()

    async def test_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_bot = MagicMock()
        fake_bot.send_message = AsyncMock(side_effect=RuntimeError("network down"))
        monkeypatch.setattr(telegram, "Bot", MagicMock(return_value=fake_bot))
        result = await notify_tools.notify_telegram("hi", token="token", chat_id="1")
        assert result == "Telegram notify failed: network down"


class TestRegisterNotifyTools:
    def test_registers_notify_tool(self) -> None:
        registry = ToolRegistry()
        notify_tools.register_notify_tools(registry)
        assert registry.count == 1
        tool = registry.get("notify")
        assert tool is not None
        assert tool.handler is notify_tools.notify_telegram
