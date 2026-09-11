from __future__ import annotations

import pytest

from raven.tools.db import _validate_select_only, db_query


class TestValidateSelectOnly:
    def test_single_select_allowed(self) -> None:
        assert _validate_select_only("SELECT 1") is None
        assert _validate_select_only("select * from users") is None
        assert _validate_select_only("SELECT name, age FROM users WHERE id = 3") is None

    def test_trailing_semicolon_allowed(self) -> None:
        assert _validate_select_only("SELECT 1;") is None
        assert _validate_select_only("SELECT 1;  -- trailing comment") is None

    def test_stacked_statements_rejected(self) -> None:
        assert _validate_select_only("SELECT 1; DELETE FROM users") is not None
        assert _validate_select_only("SELECT 1; UPDATE users SET admin = 1") is not None
        assert _validate_select_only("SELECT 1; DROP TABLE users") is not None
        assert _validate_select_only("SELECT 1; SELECT 2") is not None
        assert _validate_select_only("SELECT 1;;") is not None

    def test_non_select_rejected(self) -> None:
        assert _validate_select_only("DELETE FROM users") is not None
        assert _validate_select_only("DROP TABLE users") is not None
        assert _validate_select_only("INSERT INTO users VALUES (1)") is not None

    def test_semicolon_inside_string_is_ignored(self) -> None:
        assert _validate_select_only("SELECT ';'") is None
        assert _validate_select_only("SELECT 'a'';b'") is None
        assert _validate_select_only('SELECT "a;b"') is None

    def test_comments_are_ignored(self) -> None:
        assert _validate_select_only("-- header\nSELECT 1") is None
        assert _validate_select_only("/* block */ SELECT 1") is None
        assert _validate_select_only("SELECT '-- not a comment'") is None


@pytest.mark.asyncio
async def test_db_query_stacked_statements_blocked() -> None:
    result = await db_query("SELECT 1; UPDATE users SET admin = 1")
    assert "single SELECT" in result


@pytest.mark.asyncio
async def test_db_query_non_select_blocked() -> None:
    result = await db_query("DROP TABLE users")
    assert "Only SELECT" in result


@pytest.mark.asyncio
async def test_db_query_single_select_with_semicolon_in_string_ok() -> None:
    result = await db_query("SELECT ';'")
    assert "single SELECT" not in result and "Only SELECT" not in result
