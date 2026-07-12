from __future__ import annotations

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def notify_telegram(message: str, token: str = "", chat_id: str = "") -> str:
    if not token:
        from raven.core.channel_config import get_channel_config

        token = get_channel_config("telegram").get("bot_token", "")
    if not token:
        return "Telegram not configured (no bot token)"
    try:
        from telegram import Bot

        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message[:4000]) if chat_id else None
        return "Sent Telegram notification"
    except Exception as e:
        return f"Telegram notify failed: {e}"


def register_notify_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="notify",
            description="Send a notification to the user via Telegram",
            parameters={
                "message": {"type": "string", "description": "Message to send", "required": True},
            },
            handler=notify_telegram,
            category="communication",
        )
    )
