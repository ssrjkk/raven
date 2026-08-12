from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.asyncdb import AsyncDB, connect_backend, is_postgres_dsn
from raven.core.metrics import metrics

SendFn = Callable[[str, str, str], Awaitable[None]]


class Outbox:
    """Persistent retry queue for outbound channel messages (delivery guarantee)."""

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

    async def start(self) -> None:
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
        await self._db.commit()
        self._running = True
        self._worker = asyncio.create_task(self._run())
        logger.info("Outbox started (path={}, retry_interval={}s)", self._db_path, self._retry_interval)

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._db is not None:
            await self._db.close()
            self._db = None
        logger.info("Outbox stopped")

    async def enqueue(self, channel_id: str, session_id: str, text: str) -> None:
        if self._db is None:
            logger.warning("Outbox enqueue before start, dropping message to {}", channel_id)
            return
        now = time.time()
        await self._db.execute(
            "INSERT INTO outbox (channel_id, session_id, text, attempts, next_due, status, created_at) "
            "VALUES (?, ?, ?, 0, ?, 'pending', ?)",
            (channel_id, session_id, text, now, now),
        )
        await self._db.commit()
        metrics.inc("outbox_enqueued", {"channel": channel_id})
        logger.debug("Outbox enqueued message for {}", channel_id)

    async def _run(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._retry_interval)
                if not self._running:
                    break
                await self._process_due()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.opt(exception=True).error("Outbox worker error")

    async def _process_due(self) -> None:
        if self._db is None:
            return
        rows = await self._db.fetchall(
            "SELECT id, channel_id, session_id, text, attempts FROM outbox "
            "WHERE status = 'pending' AND next_due <= ? ORDER BY id LIMIT 100",
            (time.time(),),
        )
        for row in rows:
            await self._dispatch(row)

    async def _dispatch(self, row: Any) -> None:
        if self._db is None:
            return
        try:
            await self._send_fn(str(row["channel_id"]), str(row["session_id"]), str(row["text"]))
        except Exception as e:
            attempts = int(row["attempts"]) + 1
            if attempts >= self._max_attempts:
                async with self._db.transaction():
                    await self._db.execute(
                        "UPDATE outbox SET attempts = ?, status = 'dropped' WHERE id = ?",
                        (attempts, row["id"]),
                    )
                metrics.inc("outbox_dropped", {"channel": str(row["channel_id"])})
                logger.error(
                    "Outbox message to {} dropped after {} attempts: {}", row["channel_id"], attempts, e
                )
            else:
                async with self._db.transaction():
                    await self._db.execute(
                        "UPDATE outbox SET attempts = ?, next_due = ? WHERE id = ?",
                        (attempts, time.time() + self._backoff_base * attempts, row["id"]),
                    )
                logger.warning(
                    "Outbox retry {}/{} for {} (due in {:.0f}s)",
                    attempts,
                    self._max_attempts,
                    row["channel_id"],
                    self._backoff_base * attempts,
                )
        else:
            async with self._db.transaction():
                await self._db.execute("DELETE FROM outbox WHERE id = ?", (row["id"],))
            metrics.inc("outbox_delivered", {"channel": str(row["channel_id"])})
            logger.info("Outbox delivered message to {}", row["channel_id"])

    async def pending_count(self) -> int:
        return await self._count_by_status("pending")

    async def dropped_count(self) -> int:
        return await self._count_by_status("dropped")

    async def _count_by_status(self, status: str) -> int:
        if self._db is None:
            return 0
        row = await self._db.fetchone("SELECT COUNT(*) AS c FROM outbox WHERE status = ?", (status,))
        return int(row["c"]) if row is not None else 0

    async def flush(self) -> int:
        """Immediately attempt redelivery of all due pending messages. Returns delivered count."""
        if self._db is None:
            return 0
        delivered = 0
        rows = await self._db.fetchall(
            "SELECT id, channel_id, session_id, text, attempts FROM outbox WHERE status = 'pending' ORDER BY id"
        )
        for row in rows:
            before = await self.pending_count()
            await self._dispatch(row)
            after = await self.pending_count()
            if after < before:
                delivered += 1
        return delivered

    @property
    def healthy(self) -> bool:
        return self._db is not None and self._running
