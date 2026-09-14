"""Chunked code search over the workspace, backed by BM25.

Built for large repositories where grep is noisy and the repo map only
shows structure: the workspace is split into definition-sized chunks,
indexed with the existing dependency-free BM25 engine, and queried through
the ``code_search`` tool. The index is rebuilt lazily when the workspace
fingerprint (file count + newest mtime) changes.
"""
from __future__ import annotations

import re
from pathlib import Path

from raven.core.rag.bm25 import BM25Index
from ravencode.runtime.repo_map import _CODE_SUFFIXES, _EXCLUDED_DIRS
from ravencode.runtime.workspace import get_workspace_root

_MAX_FILES = 5_000
_MAX_FILE_BYTES = 200_000
_MAX_CHUNKS = 20_000
_TOP_DEF_RE = re.compile(r"^(?:def |class |function |fn |func |public |private |impl )", re.MULTILINE)


def chunk_source(text: str) -> list[tuple[int, int, str]]:
    """Split source into (start_line, end_line, chunk) blocks.

    Prefers top-level definition boundaries so a chunk is a coherent unit;
    falls back to fixed windows for long definition-less files.
    """
    lines = text.splitlines()
    if not lines:
        return []
    starts = [i for i, line in enumerate(lines) if _TOP_DEF_RE.match(line)]
    if len(starts) < 2:
        # small or definition-less file: one chunk (or fixed windows if huge)
        if len(lines) <= 120:
            return [(1, len(lines), text)]
        starts = list(range(0, len(lines), 100))
    bounds = [*starts, len(lines)]
    chunks: list[tuple[int, int, str]] = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a > 400:  # huge block: window it
            for w in range(a, b, 200):
                chunks.append((w + 1, min(w + 200, b), "\n".join(lines[w : min(w + 200, b)])))
        else:
            chunks.append((a + 1, b, "\n".join(lines[a:b])))
    return chunks


class RepoIndex:
    def __init__(self) -> None:
        self._fingerprint: tuple[int, float] | None = None
        self._entries: list[tuple[str, int, int, str]] = []  # (relpath, start, end, text)
        self._index = BM25Index()

    def _fingerprint_of(self, root: Path) -> tuple[int, float]:
        count = 0
        newest = 0.0
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                continue
            count += 1
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        return (count, newest)

    def build(self, root: str | Path) -> None:
        root = Path(root)
        fp = self._fingerprint_of(root)
        if fp == self._fingerprint:
            return
        docs: list[str] = []
        entries: list[tuple[str, int, int, str]] = []
        files = 0
        for path in sorted(root.rglob("*")):
            if len(entries) >= _MAX_CHUNKS or files >= _MAX_FILES:
                break
            if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                continue
            rel_parts = path.relative_to(root).parts
            if any(part in _EXCLUDED_DIRS for part in rel_parts[:-1]):
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files += 1
            rel = "/".join(rel_parts)
            for start, end, chunk in chunk_source(text):
                if len(chunk.strip()) < 20:
                    continue
                entries.append((rel, start, end, chunk))
                docs.append(chunk)
        self._entries = entries
        self._index = BM25Index().fit(docs)
        self._fingerprint = fp

    def search(self, root: str | Path, query: str, k: int = 5) -> list[str]:
        self.build(root)
        if not self._entries:
            return []
        k = max(1, min(k, 20))
        scores = self._index.scores(query)
        ranked = sorted(range(len(self._entries)), key=lambda i: scores[i], reverse=True)[:k]
        results = []
        for i in ranked:
            if scores[i] <= 0:
                break
            rel, start, end, text = self._entries[i]
            results.append(f"{rel}:{start}-{end}\n{text}")
        return results


_index = RepoIndex()


async def code_search(query: str, k: int = 5) -> str:
    """Search the workspace for code relevant to a natural-language query."""
    root = get_workspace_root() or "."
    hits = _index.search(root, query, k=k)
    if not hits:
        return "[no matches — try grep for exact identifiers instead]"
    return "\n\n---\n\n".join(hits)


def reset_index() -> None:
    global _index
    _index = RepoIndex()
