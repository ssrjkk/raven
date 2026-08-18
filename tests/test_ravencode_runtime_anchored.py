from __future__ import annotations

from collections.abc import Generator

import pytest

import ravencode.runtime.anchored as anchored_mod
from ravencode.runtime.anchored import (
    anchored_summary,
    append_anchored_summary,
    clear_anchored_summary,
    update_anchored_summary,
)


@pytest.fixture(autouse=True)
def reset() -> Generator[None, None, None]:
    anchored_mod._ANCHORED_SUMMARY = ""
    yield
    anchored_mod._ANCHORED_SUMMARY = ""


class TestAnchoredSummary:
    def test_default_empty(self) -> None:
        assert anchored_summary() == ""

    def test_update(self) -> None:
        result = update_anchored_summary("hello world")
        assert result == "Anchored summary updated (11 chars)"
        assert anchored_summary() == "hello world"

    def test_append_to_empty(self) -> None:
        result = append_anchored_summary("first")
        assert result == "Anchored summary appended (5 chars)"
        assert anchored_summary() == "first"

    def test_append_to_existing(self) -> None:
        update_anchored_summary("one")
        append_anchored_summary("two")
        assert anchored_summary() == "one\ntwo"

    def test_clear(self) -> None:
        update_anchored_summary("x")
        assert clear_anchored_summary() == "(anchored summary cleared)"
        assert anchored_summary() == ""

    def test_clear_empty(self) -> None:
        assert clear_anchored_summary() == "(anchored summary cleared)"
