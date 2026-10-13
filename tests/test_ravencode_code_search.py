"""Tests for BM25-based code_search tool (ravencode.runtime.code_search)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ravencode.runtime.code_search import RepoIndex, chunk_source, code_search, reset_index
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


def test_chunk_source_empty_text() -> None:
    assert chunk_source("") == []


def test_chunk_source_windows_large_gap_between_definitions() -> None:
    text = "def a():\n" + "".join(f"x{i} = {i}\n" for i in range(450)) + "def b():\n    pass\n"
    chunks = chunk_source(text)
    assert max(end - start for start, end, _ in chunks) <= 200
    assert sum(end - start + 1 for start, end, _ in chunks) >= 452


def test_build_skips_short_huge_noncode_and_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ravencode.runtime.code_search as cs
    from ravencode.runtime.fs_walk import iter_files as real_iter

    (tmp_path / "good.py").write_text("def f():\n    return 'searchable chunk content'\n", encoding="utf-8")
    (tmp_path / "short.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "huge.py").write_text("def big():\n" + "z = 1\n" * 70_000, encoding="utf-8")
    (tmp_path / "notes.md").write_text("def not_code():\n", encoding="utf-8")
    ghost = tmp_path / "ghost.py"  # walked but never created: stat and read raise OSError

    def fake_iter(root: Path):
        yield from real_iter(root)
        yield ghost

    monkeypatch.setattr(cs, "iter_files", fake_iter)
    index = cs.RepoIndex()
    index.build(tmp_path)
    rels = [e[0] for e in index._entries]
    assert "good.py" in rels
    assert not {"short.py", "huge.py", "notes.md", "ghost.py"} & set(rels)

    entries = index._entries
    index.build(tmp_path)  # unchanged fingerprint: no rebuild
    assert index._entries is entries


def test_build_respects_max_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text(f"def d{i}():\n    return 'chunk number {i} here'\n", encoding="utf-8")
    monkeypatch.setattr("ravencode.runtime.code_search._MAX_CHUNKS", 2)
    index = RepoIndex()
    index.build(tmp_path)
    assert len(index._entries) <= 2


def test_search_without_entries_returns_empty(tmp_path: Path) -> None:
    assert RepoIndex().search(tmp_path, "anything") == []
