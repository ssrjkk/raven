from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import local as thread_local
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class IdempotencyStore:
    """Idempotency key store backed by SQLite.

    All write endpoints MUST extract X-Idempotency-Key from request headers.
    If the key was already processed, return cached response (HTTP 200).
    If the key is in-flight, return HTTP 409 Conflict.
    TTL: 24 hours after completion.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = thread_local()
        self._init_table()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        conn: sqlite3.Connection = self._local.conn
        return conn

    def _init_table(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                response_code INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency_keys(expires_at);
        """)
        self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM idempotency_keys WHERE idempotency_key = ? AND expires_at > ?",
            (key, time.time()),
        ).fetchone()
        if row:
            return {"code": row[1], "body": row[2], "status": row[3]}
        return None

    def set(self, key: str, code: int, body: str, ttl_hours: int = 24):
        now = time.time()
        self._conn.execute(
            """INSERT OR REPLACE INTO idempotency_keys
               (idempotency_key, response_code, response_body, status, created_at, expires_at)
               VALUES (?, ?, ?, 'completed', ?, ?)""",
            (key, code, body, now, now + ttl_hours * 3600),
        )
        self._conn.commit()

    def clean_expired(self):
        self._conn.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (time.time(),))
        self._conn.commit()


async def idempotency_middleware(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    idem_key = request.headers.get("X-Idempotency-Key")
    if not idem_key:
        return await call_next(request)

    store: IdempotencyStore | None = getattr(request.app.state, "idempotency_store", None)
    if store is None:
        return await call_next(request)

    existing = store.get(idem_key)
    if existing:
        if existing["status"] == "in_flight":
            return JSONResponse(status_code=409, content={"error": "Request is already being processed"})
        return JSONResponse(
            status_code=existing["code"],
            content=existing["body"],
            headers={"X-Idempotency-Key": idem_key, "X-Idempotency-Replayed": "true"},
        )

    response = await call_next(request)
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    store.set(idem_key, response.status_code, body.decode())
    return response
