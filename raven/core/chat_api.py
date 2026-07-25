from __future__ import annotations

from fastapi import APIRouter, Query
from loguru import logger

from raven.core.db import Database

# Database duck-type: expects async `.conn.execute(sql, params)` returning async cursor with `.fetchall()`
_db: Database | None = None


def set_database(db: Database | None) -> None:
    global _db
    _db = db


def create_chat_router() -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.get("/search")
    async def search_chat(q: str = Query("", min_length=1), limit: int = Query(50, ge=1, le=200)):
        if not _db or not hasattr(_db, "conn"):
            return {"results": [], "total": 0}
        try:
            pattern = f"%{q}%"
            sql = """
                SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                       COALESCE(s.name, '') as session_name
                FROM messages m
                LEFT JOIN sessions s ON s.id = m.session_id
                WHERE m.content LIKE ?
                ORDER BY m.created_at DESC
                LIMIT ?
            """
            async with _db.conn.execute(sql, (pattern, limit)) as c:
                rows = await c.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row["id"],
                        "session_id": row["session_id"],
                        "role": row["role"],
                        "content": row["content"],
                        "session_name": row["session_name"],
                        "created_at": row["created_at"],
                    }
                )
            return {"results": results, "total": len(results), "query": q}
        except Exception as e:
            logger.warning("[chat] search failed: {}", e)
            return {"results": [], "total": 0, "error": str(e)}

    return router
