from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import rag as rag_mod


class _FakeRag:
    def __init__(self, results: list[Any] | None = None, removed: bool = True) -> None:
        self._results = results or []
        self._removed = removed
        self.saved = 0
        self.loaded = 0
        self.indexed: list[Any] = []

    def set_index_path(self, _p: str) -> None:
        return None

    def load_index(self) -> None:
        self.loaded += 1

    def save_index(self) -> None:
        self.saved += 1

    def index_document(self, doc: Any) -> list[str]:
        self.indexed.append(doc)
        return ["c1", "c2"]

    def search(self, _q: str, top_k: int = 5, include_images: bool = True) -> list[Any]:
        return self._results

    def get_stats(self) -> dict[str, Any]:
        return {
            "documents": 3,
            "chunks": 12,
            "total_chars": 4567,
            "total_images": 2,
            "sentence_transformer": True,
            "clip_available": False,
            "chroma_available": True,
        }

    def remove_document(self, _did: str) -> bool:
        return self._removed


def _sr(modality: str, score: float, doc_id: str, text: str, image: str = "") -> SimpleNamespace:
    return SimpleNamespace(modality=modality, score=score, document_id=doc_id, text=text, image_path=image)


class TestGetRag:
    def test_creates_and_loads_when_index_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        idx = tmp_path / "rag.json"
        idx.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(rag_mod, "_rag", None)
        monkeypatch.setattr(rag_mod, "_RAG_PATH", idx)
        fake: Any = _FakeRag()
        monkeypatch.setattr(rag_mod, "MultiModalRAG", lambda: fake)
        rag = rag_mod._get_rag()
        assert fake.loaded == 1
        assert rag is fake

    def test_skips_load_when_no_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rag_mod, "_rag", None)
        monkeypatch.setattr(rag_mod, "_RAG_PATH", Path("Z:/definitely/missing/rag.json"))
        fake: Any = _FakeRag()
        monkeypatch.setattr(rag_mod, "MultiModalRAG", lambda: fake)
        rag = rag_mod._get_rag()
        assert fake.loaded == 0
        assert rag is fake

    def test_load_error_is_swallowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        idx = tmp_path / "rag.json"
        idx.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(rag_mod, "_rag", None)
        monkeypatch.setattr(rag_mod, "_RAG_PATH", idx)

        class _BoomRag(_FakeRag):
            def load_index(self) -> None:
                raise RuntimeError("corrupt")

        fake: Any = _BoomRag()
        monkeypatch.setattr(rag_mod, "MultiModalRAG", lambda: fake)
        assert rag_mod._get_rag() is fake


class TestSaveRag:
    def test_save_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag()
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        rag_mod._save_rag()
        assert fake.saved == 1

    def test_save_error_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _BoomRag(_FakeRag):
            def save_index(self) -> None:
                raise RuntimeError("disk")

        monkeypatch.setattr(rag_mod, "_get_rag", lambda: _BoomRag())
        rag_mod._save_rag()  # must not raise


class TestRagIndexText:
    def test_valid_json_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag()
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        out = rag_mod.rag_index_text("d1", "text", source="s", metadata='{"a": 1}')
        assert out == "Indexed 2 chunks from document 'd1'."
        assert fake.indexed[0].metadata == {"a": 1}
        assert fake.saved == 1

    def test_invalid_metadata_becomes_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag()
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        rag_mod.rag_index_text("d2", "t", metadata="not-json")
        assert fake.indexed[0].metadata == {"note": "not-json"}

    def test_empty_metadata_is_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag()
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        rag_mod.rag_index_text("d3", "t")
        assert fake.indexed[0].metadata == {}


class TestRagSearch:
    def test_formats_text_and_image_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        results = [
            _sr("text", 0.51234, "docA", "some\nsnippet"),
            _sr("image", 0.9, "docB", "caption", image="/img/p.png"),
        ]
        fake = _FakeRag(results=results)
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        out = rag_mod.rag_search("q")
        assert "Search results for 'q'" in out
        assert "score=0.9000 | doc=docB" in out
        assert "[IMAGE]" in out
        assert "image: /img/p.png" in out

    def test_empty_text_snippet_line_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag(results=[_sr("text", 0.1, "docZ", "")])
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        out = rag_mod.rag_search("q")
        assert "doc=docZ" in out

    def test_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag(results=[])
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        assert rag_mod.rag_search("q") == "No results for 'q'."

    def test_search_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _BoomRag(_FakeRag):
            def search(self, _q: str, top_k: int = 5, include_images: bool = True) -> list[Any]:
                raise ValueError("embed fail")

        monkeypatch.setattr(rag_mod, "_get_rag", lambda: _BoomRag())
        assert "[error] Search failed" in rag_mod.rag_search("q")


class TestRagStatsAndRemove:
    def test_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: _FakeRag())
        out = rag_mod.rag_stats()
        assert "Documents: 3" in out
        assert "SentenceTransformer: available" in out
        assert "CLIP: not available" in out
        assert "ChromaDB: available" in out

    def test_remove_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeRag(removed=True)
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: fake)
        assert rag_mod.rag_remove_document("d") == "Document 'd' removed."
        assert fake.saved == 1

    def test_remove_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rag_mod, "_get_rag", lambda: _FakeRag(removed=False))
        assert rag_mod.rag_remove_document("x") == "[error] Document 'x' not found."


class TestRegistration:
    def test_registers_four_tools(self) -> None:
        registry = ToolRegistry()
        rag_mod.register_rag_tools(registry)
        for name in ("rag_index_text", "rag_search", "rag_stats", "rag_remove_document"):
            assert registry.get(name) is not None
