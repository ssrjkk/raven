from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from raven.channels.base import BaseChannel


class ChannelManager:
    def __init__(self) -> None:
        self._channels: dict[str, BaseChannel] = {}
        self._lock = asyncio.Lock()

    async def register(self, channel: BaseChannel) -> None:
        async with self._lock:
            self._channels[channel.channel_id] = channel
        logger.info("Registered channel: {}", channel.channel_id)

    async def get(self, channel_id: str) -> BaseChannel | None:
        async with self._lock:
            return self._channels.get(channel_id)

    async def remove(self, channel_id: str) -> BaseChannel | None:
        async with self._lock:
            return self._channels.pop(channel_id, None)

    async def list_ids(self) -> list[str]:
        async with self._lock:
            return list(self._channels.keys())

    async def start_all(self) -> None:
        async with self._lock:
            channels = list(self._channels.items())
        for cid, channel in channels:
            try:
                await channel.start()
                logger.info("Channel started: {}", cid)
            except Exception as e:
                logger.error("Failed to start channel {}: {}", cid, e)

    async def stop_all(self) -> None:
        async with self._lock:
            channels = list(self._channels.items())
        for cid, channel in channels:
            try:
                await channel.stop()
                logger.info("Channel stopped: {}", cid)
            except Exception as e:
                logger.error("Error stopping channel {}: {}", cid, e)

    def __contains__(self, channel_id: str) -> bool:
        return channel_id in self._channels

    def __getitem__(self, channel_id: str) -> BaseChannel:
        return self._channels[channel_id]
