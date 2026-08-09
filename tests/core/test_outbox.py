from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from raven.core.outbox import Outbox


async def _always_fail(channel_id: str, session_id: str, text: str) -> None:
    raise RuntimeError(f"delivery failed: {channel_id}")


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "outbox.db")


async def test_enqueue_tracks_pending(db_path: str) -> None:
    sent: list[tuple[str, str, str]] = []

    async def send(channel_id: str, session_id: str, text: str) -> None:
        sent.append((channel_id, session_id, text))

    box = Outbox(db_path, send)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        await box.enqueue("discord", "s2", "world")
        assert await box.pending_count() == 2
        assert await box.dropped_count() == 0
        await box.flush()
        assert sent == [("telegram", "s1", "hello"), ("discord", "s2", "world")]
        assert await box.pending_count() == 0
    finally:
        await box.stop()


async def test_flaky_delivery_retries_then_succeeds(db_path: str) -> None:
    attempts = {"n": 0}

    async def flaky_send(channel_id: str, session_id: str, text: str) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient failure")

    box = Outbox(db_path, flaky_send, max_attempts=5, backoff_base=0.0)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        assert await box.flush() == 0
        assert await box.pending_count() == 1
        assert await box.flush() == 0
        assert await box.pending_count() == 1
        assert await box.flush() == 1
        assert await box.pending_count() == 0
        assert attempts["n"] == 3
    finally:
        await box.stop()


async def test_max_attempts_drops_message(db_path: str) -> None:
    box = Outbox(db_path, _always_fail, max_attempts=3, backoff_base=0.0)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        for _ in range(3):
            await box.flush()
        assert await box.pending_count() == 0
        assert await box.dropped_count() == 1
    finally:
        await box.stop()


async def test_worker_delivers_after_retry_interval(db_path: str) -> None:
    attempts = {"n": 0}

    async def flaky_send(channel_id: str, session_id: str, text: str) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient failure")

    box = Outbox(db_path, flaky_send, max_attempts=3, retry_interval=0.1, backoff_base=0.0)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        for _ in range(20):
            if await box.pending_count() == 0:
                break
            await asyncio.sleep(0.1)
        assert await box.pending_count() == 0
        assert await box.dropped_count() == 0
    finally:
        await box.stop()


async def test_persistence_across_restart(db_path: str) -> None:
    async def send(channel_id: str, session_id: str, text: str) -> None:
        raise RuntimeError("down")

    box = Outbox(db_path, send, max_attempts=5, backoff_base=0.0)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        assert await box.pending_count() == 1
    finally:
        await box.stop()

    box2 = Outbox(db_path, send, max_attempts=5, backoff_base=0.0)
    await box2.start()
    try:
        assert await box2.pending_count() == 1
    finally:
        await box2.stop()


async def test_enqueue_before_start_is_noop(db_path: str) -> None:
    async def send(channel_id: str, session_id: str, text: str) -> None:
        raise AssertionError("should not be called")

    box = Outbox(db_path, send)
    await box.enqueue("telegram", "s1", "hello")
    assert await box.pending_count() == 0
    assert box.healthy is False
