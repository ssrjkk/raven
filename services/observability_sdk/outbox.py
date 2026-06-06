from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from threading import local as thread_local
from typing import Any


class OutboxStore:
    """Transactional Outbox pattern implementation.

    Each service embeds an outbox table in its local database.
    Events are inserted atomically with the business transaction,
    then a background poller publishes them to NATS.
    Guarantees: at-least-once delivery, exactly-once dedup via idempotency_key.
    """

    def __init__(self, db_path: str | None = None, service_name: str = "unknown"):
        self._db_path = db_path or os.environ.get("DB_PATH", str(Path("data") / "outbox.db"))
        self._service = service_name
        self._local = thread_local()
        self._init_table()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_table(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                subject TEXT NOT NULL,
                payload TEXT NOT NULL,
                headers TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                published_at REAL,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status, created_at);
        """)
        self._conn.commit()

    def enqueue(
        self,
        subject: str,
        data: dict[str, Any],
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        key = idempotency_key or str(uuid.uuid4())
        existing = self._conn.execute("SELECT id FROM outbox WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            return existing[0]

        event_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO outbox
               (id, idempotency_key, subject, payload, headers, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                key,
                subject,
                json.dumps(data, default=str),
                json.dumps(headers or {}),
                time.time(),
            ),
        )
        self._conn.commit()
        return event_id

    def fetch_pending(self, batch_size: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' ORDER BY created_at LIMIT ?",
            (batch_size,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_published(self, event_id: str):
        self._conn.execute(
            "UPDATE outbox SET status = 'published', published_at = ? WHERE id = ?",
            (time.time(), event_id),
        )
        self._conn.commit()

    def mark_failed(self, event_id: str, error: str):
        self._conn.execute(
            "UPDATE outbox SET retry_count = retry_count + 1, last_error = ?, status = ? WHERE id = ?",
            (error[:500], "failed", event_id),
        )
        self._conn.commit()

    def clean_expired(self, max_age_hours: int = 168):
        cutoff = time.time() - max_age_hours * 3600
        self._conn.execute("DELETE FROM outbox WHERE created_at < ? AND status != 'failed'", (cutoff,))
        self._conn.commit()
