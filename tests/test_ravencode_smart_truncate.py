"""Tests for smart tool-result truncation (middle-out + spill)."""
from __future__ import annotations

from pathlib import Path

from ravencode.runtime.tools import smart_truncate
from ravencode.runtime.workspace import set_workspace_root


def test_short_result_passes_through(tmp_path: Path) -> None:
    set_workspace_root(tmp_path)
    try:
        text = "short output"
        assert smart_truncate(text, limit=10_000) == text
    finally:
        set_workspace_root(None)


def test_long_result_keeps_head_and_tail(tmp_path: Path) -> None:
    set_workspace_root(tmp_path)
    try:
        limit = 1_000
        text = "HEAD" + "m" * 5_000 + "TAIL"
        out = smart_truncate(text, limit=limit)
        assert len(out) < len(text)
        assert out.startswith("HEAD")
        assert out.endswith("TAIL")
        assert "chars truncated" in out
    finally:
        set_workspace_root(None)


def test_long_result_spills_to_disk(tmp_path: Path) -> None:
    set_workspace_root(tmp_path)
    try:
        text = "x" * 20_000
        out = smart_truncate(text, limit=2_000)
        assert "full output saved to" in out
        spill_dir = tmp_path / ".raven" / "spill"
        files = list(spill_dir.glob("tool_*.txt"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == text
    finally:
        set_workspace_root(None)


def test_spill_failure_is_not_fatal(tmp_path: Path) -> None:
    # workspace root pointing at a plain file makes spill dir creation fail
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    set_workspace_root(blocker)
    try:
        out = smart_truncate("y" * 20_000, limit=1_000)
        assert out.startswith("y")
        assert out.endswith("y")
        assert "full output saved" not in out
        assert "chars truncated" in out
    finally:
        set_workspace_root(None)
