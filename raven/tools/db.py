from __future__ import annotations

import json
import os
import re
from pathlib import Path

import aiosqlite
from loguru import logger

from raven.core.asyncdb import postgres_dsn
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def _mask_sql_quotes(sql: str) -> str:
    """Replace string/comment contents with spaces so delimiters inside are ignored."""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue
        if c in ("'", '"', "`"):
            quote = c
            i += 1
            while i < n:
                if sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _validate_select_only(query: str) -> str | None:
    """Reject anything but a single SELECT statement (blocks stacked statements)."""
    masked = _mask_sql_quotes(query)
    if not re.match(r"(?is)^\s*SELECT\b", masked):
        return "Only SELECT queries are allowed for security reasons"
    semi = masked.find(";")
    if semi != -1 and masked[semi + 1 :].strip():
        return "Only a single SELECT statement is allowed"
    return None


def _is_allowed_path(p: Path, data_dir: Path, ws: Path) -> bool:
    try:
        p.relative_to(data_dir)
        return True
    except ValueError:
        pass
    try:
        p.relative_to(ws)
        return True
    except ValueError:
        pass
    return False


async def db_query(query: str, db_path: str = "data/raven.db") -> str:
    stripped = query.strip()
    validation_error = _validate_select_only(stripped)
    if validation_error is not None:
        return validation_error

    dsn = postgres_dsn()
    if dsn:
        try:
            import asyncpg

            async with asyncpg.connect(dsn) as conn:
                rows = await conn.fetch(stripped)
                if not rows:
                    return "(empty result set)"
                result = [dict(r) for r in rows[:100]]
                return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("DB query failed: {}", e)
            return f"Query error: {e}"

    from raven.core.config import settings

    data_dir = settings.resolved_db_path.parent.resolve()
    ws = Path(os.environ.get("RAVEN_WORKSPACE", "data")).resolve()

    p = Path(db_path)
    if p.is_absolute() or p.drive or p.root:
        p = p.expanduser().resolve()
        if not p.exists():
            return f"Database not found: {p}"
        if not _is_allowed_path(p, data_dir, ws):
            return f"Access denied: path outside data directory: {p}"
    else:
        base = settings.resolved_db_path.parent.parent.resolve()
        p = (base / p).resolve()
        if not p.exists():
            return f"Database not found: {p}"
        if not _is_allowed_path(p, data_dir, ws):
            return f"Access denied: path outside data directory: {p}"

    async with aiosqlite.connect(str(p)) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            cursor = await conn.execute(stripped)
            rows = await cursor.fetchmany(100)
            if not rows:
                return "(empty result set)"
            columns = [d[0] for d in cursor.description]
            result = [dict(zip(columns, row, strict=False)) for row in rows]
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("DB query failed: {}", e)
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
            dangerous=True,
            allowed_roles=["admin"],
        )
    )
