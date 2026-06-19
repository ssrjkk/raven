from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def db_query(query: str, db_path: str = "data/raven.db") -> str:
    p = Path(db_path).expanduser().resolve()
    if not p.exists():
        return f"Database not found: {p}"

    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        return "Only SELECT queries are allowed for security reasons"

    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query)
        rows = cursor.fetchmany(100)
        if not rows:
            return "(empty result set)"
        columns = [d[0] for d in cursor.description]
        result = [dict(zip(columns, row, strict=False)) for row in rows]
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Query error: {e}"
    finally:
        conn.close()


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
