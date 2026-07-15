from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def db_query(query: str, db_path: str = "data/raven.db") -> str:
    from raven.core.config import settings
    p = Path(db_path)
    if not p.is_absolute() and not p.drive and not p.root:
        base = settings.resolved_db_path.parent.parent.resolve()
        data_dir = settings.resolved_db_path.parent.resolve()
        p = (base / p).resolve()
        try:
            p.relative_to(data_dir)
        except ValueError:
            return f"Access denied: path outside data directory: {p}"
    else:
        p = p.expanduser().resolve()
    if not p.exists():
        return f"Database not found: {p}"

    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        return "Only SELECT queries are allowed for security reasons"

    async with aiosqlite.connect(str(p)) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            cursor = await conn.execute(query)
            rows = await cursor.fetchmany(100)
            if not rows:
                return "(empty result set)"
            columns = [d[0] for d in cursor.description]
            result = [dict(zip(columns, row, strict=False)) for row in rows]
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Query error: {e}"


def register_db_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="db_query",
            description="Execute a SQL query on the Raven database",
            parameters={
                "query": {"type": "string", "description": "SQL query to execute", "required": True},
                "db_path": {"type": "string", "description": "Path to SQLite database", "required": False},
            },
            handler=db_query,
            category="data",
        )
    )
