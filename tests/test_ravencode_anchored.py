from __future__ import annotations

import ravencode.runtime.anchored as anchored_mod
from ravencode.runtime.anchored import (
    anchored_summary,
    append_anchored_summary,
    clear_anchored_summary,
    update_anchored_summary,
)


def _setup():
    anchored_mod._ANCHORED_SUMMARY = ""


class TestAnchoredSummary:
    def test_read_empty(self):
        _setup()
        assert anchored_summary() == ""

    def test_write_and_read(self):
        _setup()
        update_anchored_summary("hello world")
        assert anchored_summary() == "hello world"

    def test_write_overwrites(self):
        _setup()
        update_anchored_summary("first")
        update_anchored_summary("second")
        assert anchored_summary() == "second"

    def test_append(self):
        _setup()
        update_anchored_summary("hello")
        append_anchored_summary(" world")
        assert anchored_summary() == "hello\n world"

    def test_append_empty(self):
        _setup()
        append_anchored_summary("only")
        assert anchored_summary() == "only"

    def test_clear(self):
        _setup()
        update_anchored_summary("something")
        clear_anchored_summary()
        assert anchored_summary() == ""

    def test_clear_empty(self):
        _setup()
        clear_anchored_summary()
        assert anchored_summary() == ""

    def test_write_returns_message(self):
        _setup()
        result = update_anchored_summary("new summary")
        assert "updated" in result

    def test_append_returns_summary(self):
        _setup()
        update_anchored_summary("base")
        result = append_anchored_summary(". appended")
        assert len(result) > 0

    def test_clear_returns_message(self):
        _setup()
        update_anchored_summary("x")
        result = clear_anchored_summary()
        assert "cleared" in result
