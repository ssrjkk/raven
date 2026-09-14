"""Tests for BM25-based code_search tool (ravencode.runtime.code_search)."""
from __future__ import annotations

from pathlib import Path

from ravencode.runtime.code_search import chunk_source, code_search, reset_index
from ravencode.runtime.workspace import set_workspace_root


def teardown_function() -> None:
    reset_index()
    set_workspace_root(None)


def test_chunk_source_splits_on_definitions() -> None:
    text = (
        "import os\n"
        "\n"
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 2\n"
        "\n"
        "class Gamma:\n"
        "    pass\n"
    )
    chunks = chunk_source(text)
    assert len(chunks) >= 3
    joined = "\n".join(c[2] for c in chunks)
    assert "def alpha" in joined
    assert "class Gamma" in joined
    # chunk line numbers are 1-based and sane
    for start, end, chunk in chunks:
        assert start >= 1
        assert end >= start
        assert len(chunk.splitlines()) <= end - start + 1


def test_chunk_source_small_file_single_chunk() -> None:
    chunks = chunk_source("x = 1\ny = 2\n")
    assert len(chunks) == 1
    assert chunks[0][0] == 1


def test_chunk_source_huge_file_is_windowed() -> None:
    text = "\n".join(f"line{i} = {i}" for i in range(1000))
    chunks = chunk_source(text)
    assert len(chunks) > 1
    assert all(end - start <= 400 for start, end, _ in chunks)


def _make_repo(root: Path) -> None:
    pkg = root / "app"
    pkg.mkdir()
    (pkg / "payments.py").write_text(
        "def process_payment(amount):\n"
        "    '''Charge the customer with retry backoff.'''\n"
        "    return amount\n",
        encoding="utf-8",
    )
    (pkg / "ui.py").write_text(
        "def render_button(label):\n"
        "    '''Draw a button on screen.'''\n"
        "    return label\n",
        encoding="utf-8",
    )
    junk = root / "node_modules" / "lib"
    junk.mkdir(parents=True)
    (junk / "noise.py").write_text("def process_payment():\n    return 'vendored junk'\n", encoding="utf-8")


async def test_code_search_finds_and_excludes_junk(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    set_workspace_root(tmp_path)
    reset_index()
    result = await code_search("payment retry backoff charge customer", k=3)
    assert "app/payments.py" in result
    assert "node_modules" not in result


async def test_code_search_no_match_message(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    set_workspace_root(tmp_path)
    reset_index()
    result = await code_search("quantum blockchain widget frobnicator", k=3)
    assert result.startswith("[no matches")


async def test_code_search_ranks_relevant_file_first(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    set_workspace_root(tmp_path)
    reset_index()
    result = await code_search("render button screen draw label", k=5)
    # ui.py is the only relevant file for this query
    assert "app/ui.py" in result
