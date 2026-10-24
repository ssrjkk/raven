from __future__ import annotations

import asyncio
import time
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


async def test_purge_dropped_removes_old_rows(db_path: str) -> None:
    box = Outbox(db_path, _always_fail, max_attempts=3, backoff_base=0.0)
    await box.start()
    try:
        await box.enqueue("telegram", "s1", "hello")
        for _ in range(3):
            await box.flush()
        assert await box.dropped_count() == 1

        old = time.time() - Outbox._DROPPED_RETENTION_DAYS * 86400 - 60
        assert box._db is not None
        await box._db.execute("UPDATE outbox SET created_at = ? WHERE status = 'dropped'", (old,))
        await box._db.commit()

        await box._purge_dropped()
        assert await box.dropped_count() == 0
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
    assert await box.enqueue("telegram", "s1", "hello") is False
    assert await box.pending_count() == 0
    assert box.healthy is False


async def _seed(
    box: Outbox,
    session_id: str,
    text: str,
    *,
    status: str = "pending",
    next_due: float = 0.0,
) -> None:
    assert box._db is not None
    await box._db.execute(
        "INSERT INTO outbox (channel_id, session_id, text, attempts, next_due, status, created_at) "
        "VALUES ('telegram', ?, ?, 0, ?, ?, ?)",
        (session_id, text, next_due, status, time.time()),
    )
    await box._db.commit()


class TestClaimAndLease:
    async def test_second_worker_skips_a_claimed_row(self, tmp_path: Path) -> None:
        path = str(tmp_path / "outbox.db")
        sent: list[str] = []

        async def slow_send(channel_id: str, session_id: str, text: str) -> None:
            sent.append(text)
            await asyncio.sleep(0.2)
            raise RuntimeError("channel down")

        a = Outbox(path, slow_send, retry_interval=3600.0, backoff_base=0.0)
        b = Outbox(path, slow_send, retry_interval=3600.0, backoff_base=0.0)
        await a.start()
        await b.start()
        try:
            await _seed(a, "s1", "one message")
            await asyncio.gather(a._process_due(), b._process_due())
            assert sent == ["one message"]
            assert await a.pending_count() == 1
            assert a._db is not None
            row = await a._db.fetchone("SELECT attempts FROM outbox")
            assert row is not None
            assert int(row["attempts"]) == 1
        finally:
            await a.stop()
            await b.stop()

    async def test_expired_lease_is_reclaimed_and_delivered(self, db_path: str) -> None:
        sent: list[str] = []

        async def send(channel_id: str, session_id: str, text: str) -> None:
            sent.append(text)

        box = Outbox(db_path, send, retry_interval=3600.0)
        await box.start()
        try:
            # a worker that died mid-send leaves the row owned with its lease already spent
            await _seed(box, "s1", "orphan", status="in_flight", next_due=time.time() - 1.0)
            assert await box.pending_count() == 0
            await box._process_due()
            assert sent == ["orphan"]
            assert await box.pending_count() == 0
        finally:
            await box.stop()

    async def test_live_lease_is_left_alone(self, db_path: str) -> None:
        box = Outbox(db_path, _always_fail, retry_interval=3600.0)
        await box.start()
        try:
            await _seed(box, "s1", "owned", status="in_flight", next_due=time.time() + 3600.0)
            await box._process_due()
            assert box._db is not None
            row = await box._db.fetchone("SELECT status FROM outbox")
            assert row is not None
            assert row["status"] == "in_flight"
        finally:
            await box.stop()


class TestRetrySchedule:
    async def test_delay_doubles_until_the_cap(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        box = Outbox(db_path, _always_fail, retry_interval=3600.0, backoff_base=30.0)
        await box.start()
        try:
            monkeypatch.setattr(box, "_jitter", lambda base: 0.0)
            assert box._retry_delay(1) == 30.0
            assert box._retry_delay(2) == 60.0
            assert box._retry_delay(3) == 120.0
            assert box._retry_delay(9) == Outbox._BACKOFF_CAP_SECONDS
        finally:
            await box.stop()

    async def test_jitter_stays_inside_its_band(self, db_path: str) -> None:
        box = Outbox(db_path, _always_fail, retry_interval=3600.0, backoff_base=30.0)
        await box.start()
        try:
            samples = [box._jitter(100.0) for _ in range(200)]
            assert all(0.0 <= s <= 100.0 * Outbox._JITTER_FRACTION for s in samples)
            assert len({round(s, 9) for s in samples}) > 1
        finally:
            await box.stop()

    async def test_failure_reschedules_within_the_backoff_band(self, db_path: str) -> None:
        box = Outbox(db_path, _always_fail, max_attempts=5, retry_interval=3600.0, backoff_base=60.0)
        await box.start()
        try:
            await _seed(box, "s1", "x")
            await box._process_due()
            assert box._db is not None
            row = await box._db.fetchone("SELECT status, next_due, attempts FROM outbox")
            assert row is not None
            assert row["status"] == "pending"
            assert int(row["attempts"]) == 1
            wait = float(row["next_due"]) - time.time()
            assert 60.0 <= wait <= 60.0 * (1 + Outbox._JITTER_FRACTION) + 1.0
        finally:
            await box.stop()


class TestClockGuard:
    async def test_backward_step_reattaches_the_queue(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        box = Outbox(db_path, _always_fail, max_attempts=9, retry_interval=3600.0, backoff_base=30.0)
        await box.start()
        assert box._db is not None
        try:
            await _seed(box, "s1", "x")
            await box._process_due()
            scheduled = float(await box._db.fetchval("SELECT next_due FROM outbox"))
            real = time.time
            monkeypatch.setattr("raven.core.outbox.time.time", lambda: real() - 3600.0)
            await box._process_due()
            monkeypatch.undo()
            moved = float(await box._db.fetchval("SELECT next_due FROM outbox"))
            assert scheduled - moved > 3500.0
        finally:
            await box.stop()

    async def test_startup_reschedules_an_absurd_deadline(self, db_path: str) -> None:
        async def send(channel_id: str, session_id: str, text: str) -> None:
            return None

        seeded = Outbox(db_path, send, retry_interval=3600.0)
        await seeded.start()
        try:
            await _seed(seeded, "s1", "stranded", next_due=time.time() + 30 * 86400.0)
        finally:
            await seeded.stop()

        box = Outbox(db_path, send, retry_interval=3600.0)
        await box.start()
        try:
            assert box._db is not None
            assert float(await box._db.fetchval("SELECT next_due FROM outbox")) <= time.time()
            await box._process_due()
            assert await box.pending_count() == 0
        finally:
            await box.stop()


class TestLifecycle:
    async def test_flush_counts_only_messages_the_channel_accepted(self, db_path: str) -> None:
        sent: list[str] = []

        async def send(channel_id: str, session_id: str, text: str) -> None:
            if text == "doomed":
                raise RuntimeError("channel down")
            sent.append(text)

        box = Outbox(db_path, send, max_attempts=1, retry_interval=3600.0, backoff_base=0.0)
        await box.start()
        try:
            assert await box.enqueue("telegram", "s1", "delivered") is True
            assert await box.enqueue("telegram", "s2", "doomed") is True
            assert await box.flush() == 1
            assert sent == ["delivered"]
            assert await box.pending_count() == 0
            assert await box.dropped_count() == 1
        finally:
            await box.stop()

    async def test_enqueue_after_stop_reports_the_loss(self, db_path: str) -> None:
        box = Outbox(db_path, _always_fail, retry_interval=3600.0)
        await box.start()
        await box.stop()
        assert await box.enqueue("telegram", "s1", "hello") is False

        reopened = Outbox(db_path, _always_fail, retry_interval=3600.0)
        await reopened.start()
        try:
            assert await reopened.pending_count() == 0
        finally:
            await reopened.stop()

    async def test_enqueue_during_stop_does_not_reopen_the_handle(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        box = Outbox(db_path, _always_fail, retry_interval=3600.0)
        await box.start()
        assert box._db is not None
        real_close = box._db.close
        closed = asyncio.Event()
        release = asyncio.Event()

        async def slow_close() -> None:
            await real_close()
            closed.set()
            await release.wait()

        monkeypatch.setattr(box._db, "close", slow_close)
        stopping = asyncio.create_task(box.stop())
        await closed.wait()
        assert await box.enqueue("telegram", "s1", "mid stop") is False
        assert box._db is None
        release.set()
        await stopping

