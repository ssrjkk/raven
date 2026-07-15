from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest


@pytest.fixture
def _data_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary data directory and patch db_path to use it."""
    import sqlite3
    d = tmp_path / "data"
    d.mkdir()
    db_path = d / "raven.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS _dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    with patch("raven.core.config.settings.db_path", str(db_path)):
        yield d


@pytest.mark.asyncio
async def test_db_query_is_truly_async(_data_dir: Path) -> None:
    from raven.tools.db import db_query

    db_file = _data_dir / "test_async.db"
    async with aiosqlite.connect(db_file) as conn:
        await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.execute("INSERT INTO test (val) VALUES ('async_works')")
        await conn.commit()

    result = await db_query("SELECT * FROM test", db_path=str(db_file))
    assert "async_works" in result
    assert "Query error" not in result


@pytest.mark.asyncio
async def test_db_query_blocks_non_select(_data_dir: Path) -> None:
    from raven.tools.db import db_query

    db_file = _data_dir / "test_nonselect.db"
    async with aiosqlite.connect(db_file) as conn:
        await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.commit()

    result = await db_query("DELETE FROM test; SELECT 1;", db_path=str(db_file))
    assert "Only SELECT queries are allowed" in result


@pytest.mark.asyncio
async def test_db_query_access_denied_outside_data_dir(tmp_path: Path) -> None:
    from raven.tools.db import db_query

    outside = tmp_path / "outside.db"
    outside.write_text("not a real db")

    result = await db_query("SELECT 1", db_path=str(outside))
    assert "Access denied" in result or "Database not found" in result


@pytest.mark.asyncio
async def test_db_query_empty_result(_data_dir: Path) -> None:
    from raven.tools.db import db_query

    db_file = _data_dir / "empty.db"
    async with aiosqlite.connect(db_file) as conn:
        await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.commit()

    result = await db_query("SELECT * FROM test", db_path=str(db_file))
    assert "(empty result set)" in result
