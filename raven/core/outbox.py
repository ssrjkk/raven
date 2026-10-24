from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.asyncdb import AsyncDB, connect_backend, is_postgres_dsn
from raven.core.metrics import metrics

SendFn = Callable[[str, str, str], Awaitable[None]]


class Outbox:
    """Persistent retry queue for outbound channel messages (delivery guarantee).

    Delivery is at-least-once: a row is deleted only after the channel accepted it, so a crash
    between the send and the delete redelivers. The claim step keeps that window from turning into
    a systematic duplicate for every row two workers happen to look at at the same time.
    """

    _DROPPED_RETENTION_DAYS = 7
    """Dropped (failed after max_attempts) rows are purged after this age."""

    _BATCH_SIZE = 100
    """Rows attempted per tick, oldest first."""

    _LEASE_SECONDS = 300.0
    """How long a claimed row stays owned. Must exceed the slowest channel send, otherwise a live
    worker's row is reclaimed by a peer and delivered twice."""

    _BACKOFF_CAP_SECONDS = 900.0
    _JITTER_FRACTION = 0.2
    """Without jitter every row queued against a dead channel shares one deadline, so recovery
    arrives as a burst aimed straight at the provider's rate limiter."""

    _STRANDED_AFTER_SECONDS = 6 * 3600.0
    """A deadline further out than the schedule can produce means the wall clock moved back."""

    _CLOCK_STEP_SECONDS = 1.0
    """Wall clock minus monotonic clock changing by more than this is a step, not drift."""

    def __init__(
        self,
        db_path: str | Path,
        send_fn: SendFn,
        max_attempts: int = 5,
        retry_interval: float = 30.0,
        backoff_base: float = 30.0,
    ):
        self._db_path = str(db_path)
        self._send_fn = send_fn
        self._max_attempts = max_attempts
        self._retry_interval = retry_interval
        self._backoff_base = backoff_base
        self._db: AsyncDB | None = None
        self._worker: asyncio.Task[None] | None = None
        self._running = False
        self._clock_offset: float | None = None
        self._state_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._state_lock:
            if self._db is not None:
                return
            if not is_postgres_dsn(self._db_path):
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = connect_backend(self._db_path)
            await self._db.connect()
            if self._db.dialect == "postgresql":
                await self._db.execute(
                    "CREATE TABLE IF NOT EXISTS outbox ("
                    "id BIGSERIAL PRIMARY KEY,"
                    "channel_id TEXT NOT NULL,"
                    "session_id TEXT NOT NULL,"
                    "text TEXT NOT NULL,"
                    "attempts INTEGER NOT NULL DEFAULT 0,"
                    "next_due DOUBLE PRECISION NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'pending',"
                    "created_at DOUBLE PRECISION NOT NULL"
                    ")"
                )
            else:
                await self._db.execute(
                    "CREATE TABLE IF NOT EXISTS outbox ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "channel_id TEXT NOT NULL,"
                    "session_id TEXT NOT NULL,"
                    "text TEXT NOT NULL,"
                    "attempts INTEGER NOT NULL DEFAULT 0,"
                    "next_due REAL NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'pending',"
                    "created_at REAL NOT NULL"
                    ")"
                )
            self._running = True
            await self._recover()
            self._worker = asyncio.create_task(self._run())
            logger.info(
                "Outbox started (path={}, retry_interval={}s)", self._db_path, self._retry_interval
            )

    async def stop(self) -> None:
        async with self._state_lock:
            self._running = False
            db, self._db = self._db, None
            worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        if db is not None:
            await db.close()
        logger.info("Outbox stopped")

    async def enqueue(self, channel_id: str, session_id: str, text: str) -> bool:
        """Persist a message for redelivery. False when it could not be stored at all."""
        async with self._state_lock:
            db = self._db
            if db is None:
                logger.error("Outbox is not running, message to {} is lost", channel_id)
                metrics.inc("outbox_enqueue_refused", {"channel": channel_id})
                return False
            now = time.time()
            async with db.transaction():
                await db.execute(
                    "INSERT INTO outbox (channel_id, session_id, text, attempts, next_due, status, created_at) "
                    "VALUES (?, ?, ?, 0, ?, 'pending', ?)",
                    (channel_id, session_id, text, now, now),
                )
        metrics.inc("outbox_enqueued", {"channel": channel_id})
        logger.debug("Outbox enqueued message for {}", channel_id)
        return True

    async def _run(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._retry_interval)
                if not self._running:
                    break
                await self._process_due()
                await self._purge_dropped()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.opt(exception=True).error("Outbox worker error")

    async def _recover(self) -> None:
        db = self._db
        if db is None:
            return
        now = time.time()
        async with db.transaction():
            stranded = (
                await db.execute(
                    "UPDATE outbox SET next_due = ? WHERE status = 'pending' AND next_due > ?",
                    (now, now + self._STRANDED_AFTER_SECONDS),
                )
                or 0
            )
        if stranded:
            logger.warning(
                "Outbox rescheduled {} rows stranded by a clock change, retrying them now", stranded
            )
        reclaimed = await self._reclaim_expired_leases()
        if reclaimed:
            logger.warning("Outbox reclaimed {} rows whose lease expired", reclaimed)

    async def _reclaim_expired_leases(self) -> int:
        """Rows owned by a worker that died mid-send go back to the queue.

        The count is a pre-check: taking the write lock for an UPDATE that matches nothing would
        stall every other statement on this handle once per tick.
        """
        db = self._db
        if db is None:
            return 0
        now = time.time()
        if not await db.fetchval(
            "SELECT COUNT(*) FROM outbox WHERE status = 'in_flight' AND next_due <= ?", (now,)
        ):
            return 0
        async with db.transaction():
            return (
                await db.execute(
                    "UPDATE outbox SET status = 'pending' WHERE status = 'in_flight' AND next_due <= ?",
                    (now,),
                )
                or 0
            )

    async def _purge_dropped(self) -> None:
        db = self._db
        if db is None:
            return
        cutoff = time.time() - self._DROPPED_RETENTION_DAYS * 86400
        if not await db.fetchval(
            "SELECT COUNT(*) FROM outbox WHERE status = 'dropped' AND created_at < ?", (cutoff,)
        ):
            return
        async with db.transaction():
            deleted = (
                await db.execute(
                    "DELETE FROM outbox WHERE status = 'dropped' AND created_at < ?", (cutoff,)
                )
                or 0
            )
        if deleted:
            logger.info(
                "Outbox purged {} dropped messages older than {} days",
                deleted,
                self._DROPPED_RETENTION_DAYS,
            )

    async def _process_due(self) -> None:
        db = self._db
        if db is None:
            return
        await self._reanchor_after_clock_step(time.time())
        await self._reclaim_expired_leases()
        rows = await db.fetchall(
            "SELECT id, channel_id, session_id, text FROM outbox "
            "WHERE status = 'pending' AND next_due <= ? ORDER BY id LIMIT ?",
            (time.time(), self._BATCH_SIZE),
        )
        for row in rows:
            if not self._running:
                return
            await self._dispatch(row)

    async def _reanchor_after_clock_step(self, now: float) -> bool:
        """A persisted deadline is wall-clock arithmetic, so a clock stepped backwards strands the
        whole queue for the size of the step. Monotonic time shows when that happened, and the
        deadlines are re-anchored to the new clock instead of waited out."""
        offset = now - time.monotonic()
        if self._clock_offset is None:
            self._clock_offset = offset
            return False
        step = offset - self._clock_offset
        if abs(step) < self._CLOCK_STEP_SECONDS:
            return False
        self._clock_offset = offset
        db = self._db
        if db is None:
            return True
        horizon = now + self._backoff_base
        async with db.transaction():
            moved = (
                await db.execute(
                    "UPDATE outbox SET next_due = ? WHERE status = 'pending' AND next_due > ?",
                    (horizon, horizon),
                )
                or 0
            )
        if moved:
            logger.warning(
                "Outbox clock stepped by {:+.0f}s, pulled {} queued rows due within {:.0f}s",
                step,
                moved,
                self._backoff_base,
            )
        return True

    async def _claim(self, row_id: int) -> bool:
        """Take ownership of a row; only one worker's update can still see status='pending'."""
        db = self._db
        if db is None:
            return False
        async with db.transaction():
            claimed = await db.execute(
                "UPDATE outbox SET status = 'in_flight', next_due = ? "
                "WHERE id = ? AND status = 'pending'",
                (time.time() + self._LEASE_SECONDS, row_id),
            )
        return (claimed or 0) == 1

    async def _dispatch(self, row: Any) -> bool:
        """Send one row. True only when the channel accepted it."""
        row_id = int(row["id"])
        channel_id = str(row["channel_id"])
        if not await self._claim(row_id):
            return False
        db = self._db
        if db is None:
            # stop() landed while we were claiming; the lease expires and a restart retries it
            return False
        try:
            await self._send_fn(channel_id, str(row["session_id"]), str(row["text"]))
        except Exception as e:
            await self._schedule_retry(db, row_id, channel_id, e)
            return False
        async with db.transaction():
            await db.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
        metrics.inc("outbox_delivered", {"channel": channel_id})
        logger.info("Outbox delivered message to {}", channel_id)
        return True

    async def _schedule_retry(self, db: AsyncDB, row_id: int, channel_id: str, error: Exception) -> None:
        row = await db.fetchone("SELECT attempts FROM outbox WHERE id = ?", (row_id,))
        attempts = (int(row["attempts"]) if row is not None else 0) + 1
        if attempts >= self._max_attempts:
            async with db.transaction():
                await db.execute(
                    "UPDATE outbox SET attempts = ?, status = 'dropped', next_due = ? WHERE id = ?",
                    (attempts, time.time(), row_id),
                )
            metrics.inc("outbox_dropped", {"channel": channel_id})
            logger.error(
                "Outbox message to {} dropped after {} attempts: {}", channel_id, attempts, error
            )
            return
        delay = self._retry_delay(attempts)
        async with db.transaction():
            await db.execute(
                "UPDATE outbox SET attempts = ?, next_due = ?, status = 'pending' WHERE id = ?",
                (attempts, time.time() + delay, row_id),
            )
        logger.warning(
            "Outbox retry {}/{} for {} (due in {:.0f}s)",
            attempts,
            self._max_attempts,
            channel_id,
            delay,
        )

    def _jitter(self, base: float) -> float:
        return random.uniform(0.0, base * self._JITTER_FRACTION)

    def _retry_delay(self, attempts: int) -> float:
        base = min(self._backoff_base * (2.0 ** max(0, attempts - 1)), self._BACKOFF_CAP_SECONDS)
        return base + self._jitter(base)

    async def pending_count(self) -> int:
        return await self._count_by_status("pending")

    async def dropped_count(self) -> int:
        return await self._count_by_status("dropped")

    async def _count_by_status(self, status: str) -> int:
        db = self._db
        if db is None:
            return 0
        row = await db.fetchone("SELECT COUNT(*) AS c FROM outbox WHERE status = ?", (status,))
        return int(row["c"]) if row is not None else 0

    async def flush(self) -> int:
        """Attempt every pending row now, ignoring the backoff schedule. Returns delivered count."""
        db = self._db
        if db is None:
            return 0
        rows = await db.fetchall(
            "SELECT id, channel_id, session_id, text FROM outbox WHERE status = 'pending' ORDER BY id"
        )
        delivered = 0
        for row in rows:
            if await self._dispatch(row):
                delivered += 1
        return delivered

    @property
    def healthy(self) -> bool:
        return self._db is not None and self._running
