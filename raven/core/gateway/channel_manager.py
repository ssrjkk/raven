from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from raven.channels.base import BaseChannel


class ChannelManager:
    def __init__(self) -> None:
        self.channels: dict[str, BaseChannel] = {}
        self._lock = asyncio.Lock()

    def register(self, channel: BaseChannel) -> None:
        self.channels[channel.channel_id] = channel
        logger.info("Registered channel: {}", channel.channel_id)

    def get(self, channel_id: str) -> BaseChannel | None:
        return self.channels.get(channel_id)

    def remove(self, channel_id: str) -> BaseChannel | None:
        return self.channels.pop(channel_id, None)

    def list_ids(self) -> list[str]:
        return list(self.channels.keys())

    async def start_all(self) -> None:
        for cid, channel in list(self.channels.items()):
            try:
                await channel.start()
                logger.info("Channel started: {}", cid)
            except Exception as e:
                logger.error("Failed to start channel {}: {}", cid, e)

    async def stop_all(self) -> None:
        async with self._lock:
            channels = list(self.channels.items())
        for cid, channel in channels:
            try:
                await channel.stop()
                logger.info("Channel stopped: {}", cid)
            except Exception as e:
                logger.error("Error stopping channel {}: {}", cid, e)

    def __contains__(self, channel_id: str) -> bool:
        return channel_id in self.channels

    def __getitem__(self, channel_id: str) -> BaseChannel:
        return self.channels[channel_id]
