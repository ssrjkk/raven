"""Which python-telegram-bot handler claims a message decides whether the gateway ever sees it.

Nothing checked that. `filters.TEXT & ~filters.COMMAND` excludes slash text, and no CommandHandler
covered /verbose, /task, /status and the rest of the registry, so 18 commands typed on the flagship
channel were dropped inside the SDK.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from telegram import Update, User

from raven.channels.telegram.channel import TelegramChannel

GATEWAY_COMMANDS = (
    "/verbose on",
    "/trace on",
    "/usage tokens",
    "/activation mention",
    "/think low",
    "/status",
    "/task list",
    "/code",
    "/monitor list",
    "/routine list",
    "/voice providers",
    "/compact",
    "/mcp",
    "/skills",
    "/agent coder",
    "/agent_status",
    "/restart",
    "/help",
)

ADAPTER_COMMANDS = (
    ("/start", "_cmd_start"),
    ("/new", "_cmd_new"),
    ("/reset", "_cmd_reset"),
    ("/pair ABC", "_cmd_pair"),
    ("/menu", "_cmd_menu"),
)


@pytest.fixture
def channel():
    return TelegramChannel()


def _wire(channel: TelegramChannel) -> tuple[Any, list[Any]]:
    app = TelegramChannel._build_test_app("12345:AAoffline-token-for-routing-checks")
    # the identity the SDK only learns from get_me, which routing needs to see who is addressed
    app.bot._bot_user = User(id=12345, is_bot=True, first_name="Raven", username="raven_bot")
    channel._register_handlers(app)
    handlers = [handler for group in app.handlers.values() for handler in group]
    return app, handlers


def _command_update(app: Any, text: str) -> Update:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1762000000,
            "chat": {"id": -100, "type": "group", "title": "Room"},
            "from": {"id": 2, "is_bot": False, "first_name": "someone"},
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split(" ")[0])}],
        },
    }
    return Update.de_json(payload, app.bot)


def _plain_update(app: Any, text: str) -> Update:
    payload = {
        "update_id": 2,
        "message": {
            "message_id": 2,
            "date": 1762000000,
            "chat": {"id": -100, "type": "group", "title": "Room"},
            "from": {"id": 2, "is_bot": False, "first_name": "someone"},
            "text": text,
        },
    }
    return Update.de_json(payload, app.bot)


def _claims(handlers: list[Any], update: Update) -> Any:
    """python-telegram-bot runs at most one handler per group, in registration order, so the first
    filter that matches is the whole answer to 'who sees this message'."""
    for handler in handlers:
        if handler.check_update(update):
            return handler
    return None


def test_every_gateway_command_is_claimed_by_a_handler(channel: TelegramChannel) -> None:
    app, handlers = _wire(channel)
    for text in GATEWAY_COMMANDS:
        handler = _claims(handlers, _command_update(app, text))
        assert handler is not None, f"{text} reaches nothing"
        assert handler.callback == channel._on_command, text


def test_the_adapter_still_answers_its_own_commands(channel: TelegramChannel) -> None:
    """The catch-all is registered after them, so the button-backed commands keep their own code
    instead of being forwarded twice."""
    app, handlers = _wire(channel)
    for text, attribute in ADAPTER_COMMANDS:
        handler = _claims(handlers, _command_update(app, text))
        assert handler is not None, text
        assert handler.callback == getattr(channel, attribute), text


def test_plain_text_still_goes_to_the_text_handler(channel: TelegramChannel) -> None:
    app, handlers = _wire(channel)
    handler = _claims(handlers, _plain_update(app, "what is the weather"))
    assert handler is not None
    assert handler.callback == channel._on_text


async def test_the_catch_all_forwards_the_text_as_typed(channel: TelegramChannel) -> None:
    app, _handlers = _wire(channel)
    received: list[Any] = []

    async def _record(event: Any) -> None:
        received.append(event)

    channel._handler = _record
    channel._app = app
    update = _command_update(app, "/verbose on")
    await channel._on_command(update, MagicMock(args=["on"]))
    assert [event.text for event in received] == ["/verbose on"]
    assert received[0].metadata["chat_type"] == "group"
    assert received[0].metadata["mentioned"] is False
