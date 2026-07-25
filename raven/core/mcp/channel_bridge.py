from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

SendMessageFn = Callable[[str, str, str], Awaitable[None]]


class ChannelBridge:
    def __init__(self, send_fn: SendMessageFn | None = None):
        self._send_fn = send_fn
        self._channel_registry = ToolRegistry()

    def set_send_fn(self, send_fn: SendMessageFn) -> None:
        self._send_fn = send_fn

    async def _send_message(self, channel: str, message: str, session_id: str = "default") -> str:
        if not self._send_fn:
            return "[error] ChannelBridge has no send function configured"

        max_len = 4000
        if len(message) > max_len:
            message = message[:max_len] + f"\n... (truncated, {len(message)} total chars)"

        try:
            await self._send_fn(channel, session_id, message)
            logger.info("ChannelBridge sent {}-byte message to '{}'", len(message), channel)
            return f"Message sent to channel '{channel}'"
        except Exception as exc:
            logger.error("ChannelBridge send to '{}' failed: {}", channel, exc)
            return f"[error] Failed to send to channel '{channel}': {exc}"

    async def _list_channels(self) -> str:
        return (
            "Available channels depend on the running Gateway. "
            "Common channels: telegram, slack, discord, webchat, teams, whatsapp."
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            ToolSpec(
                name="send_message",
                description="Send a message to a specific channel (telegram, slack, discord, etc.)",
                parameters={
                    "channel": {"type": "string", "description": "Target channel id", "required": True},
                    "message": {"type": "string", "description": "Message text to send", "required": True},
                    "session_id": {"type": "string", "description": "Optional session id", "required": False},
                },
                handler=self._send_message,
                category="communication",
                timeout=15,
            )
        )
        registry.register(
            ToolSpec(
                name="list_channels",
                description="List available communication channels",
                parameters={},
                handler=self._list_channels,
                category="communication",
            )
        )
