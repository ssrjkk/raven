from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel

HEARTBEAT_INTERVAL = 30.0
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_BASE = 5.0
MAX_RESTART_ATTEMPTS = 3


class TokenBucket:
    def __init__(self, rate: float = 10.0, burst: int | None = None):
        self._rate = rate
        self._burst = burst or int(rate * 2)
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(float(self._burst), self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class ChannelGuardian:
    def __init__(self, on_channel_dead: Callable[[str], Awaitable[None]] | None = None, backoff_base: float = BACKOFF_BASE):
        self._on_channel_dead = on_channel_dead
        self._backoff_base = backoff_base
        self._channels: dict[str, BaseChannel] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._channel_buckets: dict[str, TokenBucket] = {}
        self._user_buckets: dict[str, TokenBucket] = {}
        self._error_counts: dict[str, int] = {}
        self._dead_channels: set[str] = set()
        self._restart_attempts: dict[str, int] = {}
        self._start_lock = asyncio.Lock()

    def register(self, channel: BaseChannel) -> None:
        cid = channel.channel_id
        self._channels[cid] = channel
        try:
            from raven.core.config import settings
            rate = float(settings.rate_limit_max) / max(float(settings.rate_limit_window), 1.0)
        except Exception:
            logger.debug("Failed to load rate_limit config, defaulting to 10.0")
            rate = 10.0
        self._channel_buckets[cid] = TokenBucket(rate=rate)
        self._error_counts[cid] = 0
        self._restart_attempts[cid] = 0

    def unregister(self, channel_id: str) -> None:
        self._channels.pop(channel_id, None)
        self._channel_buckets.pop(channel_id, None)
        self._error_counts.pop(channel_id, None)
        self._restart_attempts.pop(channel_id, None)
        self._dead_channels.discard(channel_id)
        task = self._heartbeat_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()

    async def start(self) -> None:
        async with self._start_lock:
            for cid in list(self._channels):
                if cid not in self._heartbeat_tasks or self._heartbeat_tasks[cid].done():
                    self._heartbeat_tasks[cid] = asyncio.create_task(self._heartbeat_loop(cid))

    async def stop(self) -> None:
        for _, task in list(self._heartbeat_tasks.items()):
            task.cancel()
        self._heartbeat_tasks.clear()

    async def check_rate_limit(self, channel_id: str, user_id: str | None = None) -> bool:
        cb = self._channel_buckets.get(channel_id)
        if cb and not await cb.acquire():
            logger.warning("Rate limit exceeded for channel {}", channel_id)
            return False
        if user_id:
            ub = self._user_buckets.get(user_id)
            if ub is None:
                ub = TokenBucket(rate=5.0)
                self._user_buckets[user_id] = ub
            if not await ub.acquire():
                logger.warning("Rate limit exceeded for user {} on channel {}", user_id, channel_id)
                return False
        return True

    async def record_success(self, channel_id: str) -> None:
        if channel_id in self._error_counts:
            self._error_counts[channel_id] = 0

    async def record_error(self, channel_id: str) -> None:
        count = self._error_counts.get(channel_id, 0) + 1
        self._error_counts[channel_id] = count
        logger.warning("Error recorded for channel {} (count={})", channel_id, count)
        if count >= MAX_CONSECUTIVE_FAILURES and channel_id in self._channels:
            await self._try_restart(channel_id)

    async def _try_restart(self, channel_id: str) -> None:
        channel = self._channels.get(channel_id)
        if not channel:
            return
        attempts = self._restart_attempts.get(channel_id, 0)
        if attempts >= MAX_RESTART_ATTEMPTS:
            await self._mark_dead(channel_id)
            return
        self._restart_attempts[channel_id] = attempts + 1
        backoff = self._backoff_base * (2**attempts)
        logger.info("Restarting channel {} (attempt {}, backoff {}s)", channel_id, attempts + 1, backoff)
        try:
            await channel.stop()
            await asyncio.sleep(backoff)
            await channel.start()
            self._error_counts[channel_id] = 0
            logger.info("Channel {} restart succeeded", channel_id)
        except Exception as e:
            logger.error("Channel {} restart failed: {}", channel_id, e)
            self._error_counts[channel_id] = self._error_counts.get(channel_id, 0) + 1
            if self._error_counts[channel_id] >= MAX_CONSECUTIVE_FAILURES:
                await self._mark_dead(channel_id)

    async def _mark_dead(self, channel_id: str) -> None:
        if channel_id in self._dead_channels:
            return
        self._dead_channels.add(channel_id)
        logger.error("Channel {} marked as dead (consecutive failures)", channel_id)
        if self._on_channel_dead:
            try:
                await self._on_channel_dead(channel_id)
            except Exception as e:
                logger.error("on_channel_dead callback failed for {}: {}", channel_id, e)

    async def _heartbeat_loop(self, channel_id: str) -> None:
        while channel_id in self._channels and channel_id not in self._dead_channels:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            channel = self._channels.get(channel_id)
            if not channel:
                break
            try:
                healthy = await channel.health_check()
            except Exception as e:
                healthy = False
                logger.warning("Heartbeat raised for {}: {}", channel_id, e)
            if healthy:
                self._error_counts[channel_id] = 0
            else:
                await self._handle_unhealthy(channel_id)

    async def _handle_unhealthy(self, channel_id: str) -> None:
        count = self._error_counts.get(channel_id, 0) + 1
        self._error_counts[channel_id] = count
        logger.warning("Heartbeat miss {}/{} for channel {}", count, MAX_CONSECUTIVE_FAILURES, channel_id)
        if count >= MAX_CONSECUTIVE_FAILURES:
            await self._try_restart(channel_id)

    def status_report(self) -> dict[str, Any]:
        return {
            cid: {
                "alive": cid not in self._dead_channels,
                "errors": self._error_counts.get(cid, 0),
                "restart_attempts": self._restart_attempts.get(cid, 0),
            }
            for cid in self._channels
        }
