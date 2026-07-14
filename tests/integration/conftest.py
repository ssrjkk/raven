from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    os.environ["DB_PATH"] = str(path)
    return path


@pytest.fixture
async def db(db_path: Path) -> AsyncIterator[Any]:
    from raven.core.db import Database

    db = Database(db_path)
    await db.connect()
    yield db
    await db.disconnect()
