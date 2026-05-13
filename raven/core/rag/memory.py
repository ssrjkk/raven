from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from raven.core.rag.retriever import Retriever


class ConversationMemory:
    def __init__(self, db_path: Path | str, retriever: Retriever | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retriever = retriever

    async def _get_conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(str(self.db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memories (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                topics TEXT DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_mem_session
            ON conversation_memories(session_id)
        """)
        await conn.commit()
        return conn

    async def save_summary(self, session_id: str, summary: str, topics: list[str] | None = None):
        now = time.time()
        conn = await self._get_conn()
        try:
            await conn.execute("""
                INSERT INTO conversation_memories (id, session_id, summary, topics, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, topics=excluded.topics, updated_at=excluded.updated_at
            """, (session_id, session_id, summary, json.dumps(topics or []), now, now))
            await conn.commit()
        finally:
            await conn.close()
        if self.retriever:
            await self.retriever.index_text(
                f"conv:{session_id}",
                summary,
                {"type": "conversation_summary", "session_id": session_id, "topics": json.dumps(topics or [])},
            )

    async def get_summary(self, session_id: str) -> dict | None:
        conn = await self._get_conn()
        try:
            async with conn.execute("SELECT * FROM conversation_memories WHERE session_id = ?", (session_id,)) as c:
                row = await c.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            await conn.close()

    async def search(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        if self.retriever:
            return await self.retriever.retrieve(query, k=k, filter_meta={"type": "conversation_summary"})
        return []

    async def get_relevant_context(self, query: str, session_id: str | None = None, max_results: int = 3) -> str:
        results = await self.search(query, k=max_results)
        if not results:
            return ""
        parts = []
        for r in results:
            text = r.get("text", "")
            meta = r.get("metadata", {})
            sid = meta.get("session_id", "unknown")
            topics = meta.get("topics", "[]")
            if isinstance(topics, str):
                try:
                    topics_list = json.loads(topics)
                    topic_str = ", ".join(topics_list[:3])
                except Exception:
                    topic_str = ""
            else:
                topic_str = ""
            if topic_str:
                parts.append(f"[Session {sid[:12]} | Topics: {topic_str}]\n{text[:500]}")
            else:
                parts.append(f"[Session {sid[:12]}]\n{text[:500]}")
        return "\n\n---\n\n".join(parts)

    async def cleanup_old(self, max_age_days: int = 30):
        cutoff = time.time() - (max_age_days * 86400)
        conn = await self._get_conn()
        try:
            await conn.execute("DELETE FROM conversation_memories WHERE updated_at < ?", (cutoff,))
            await conn.commit()
            deleted = conn.total_changes
            if deleted:
                logger.info("Cleaned up {} old conversation memories", deleted)
        finally:
            await conn.close()
