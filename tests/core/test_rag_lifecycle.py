from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.unique.multi_modal_rag as mm
from raven.core import rag_api


class _CountingEngine:
    """Stands in for MultiModalRAG and records how many times the API built one."""

    built = 0

    def __init__(self) -> None:
        _CountingEngine.built += 1
        self.index_path: str | None = None
        self.loaded = 0
        self.searches: list[str] = []

    def set_index_path(self, path: str | Path) -> None:
        self.index_path = str(path)

    def load_index(self, path: str | Path | None = None) -> None:
        self.loaded += 1

    def save_index(self, path: str | Path | None = None) -> None:
        assert self.index_path is not None
        Path(self.index_path).write_text("{}", encoding="utf-8")

    def index_document(self, document: Any) -> list[str]:
        return ["chunk-1", "chunk-2"]

    def search(self, query: str, top_k: int = 5, include_images: bool = True) -> list[Any]:
        self.searches.append(query)
        return []


def _reset() -> None:
    rag_api._rag_engine = None
    rag_api._rag_path = None
    rag_api._rag_mtime = None
    _CountingEngine.built = 0


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(rag_api.create_rag_router())
    return TestClient(app)


def test_routes_reuse_one_engine_instead_of_building_one_each_time(tmp_path: Path) -> None:
    _reset()
    try:
        with patch.object(rag_api, "_RAG_PATH", tmp_path / "rag_index.json"), patch.object(
            rag_api, "MultiModalRAG", _CountingEngine
        ):
            client = _client()
            with client:
                assert client.post("/api/rag/index", json={"document_id": "d1", "text": "hello"}).status_code == 200
                assert client.post("/api/rag/search", json={"query": "hello", "top_k": 2}).status_code == 200
                assert client.post("/api/rag/search", json={"query": "again", "top_k": 2}).status_code == 200
        assert _CountingEngine.built == 1, "a second engine was built for a second request"
        engine: Any = rag_api._rag_engine
        assert engine is not None and engine.searches == ["hello", "again"]
    finally:
        _reset()


def test_a_write_is_not_reloaded_from_disk_that_the_same_engine_just_wrote(tmp_path: Path) -> None:
    _reset()
    target = tmp_path / "rag_index.json"
    try:
        with patch.object(rag_api, "_RAG_PATH", target), patch.object(rag_api, "MultiModalRAG", _CountingEngine):
            with _client() as client:
                client.post("/api/rag/index", json={"document_id": "d1", "text": "hello"})
                engine: Any = rag_api._rag_engine
                assert engine is not None
                assert engine.loaded == 0, "the engine read back the index it had just saved"

                client.post("/api/rag/search", json={"query": "hello", "top_k": 2})
                assert engine.loaded == 0

                # an index touched elsewhere is picked up: the mtime really moved
                stamp = target.stat().st_mtime + 120
                os.utime(target, (stamp, stamp))
                client.post("/api/rag/search", json={"query": "hello again", "top_k": 2})
                assert engine.loaded == 1
    finally:
        _reset()


def test_a_text_only_query_never_loads_the_clip_model(tmp_path: Path) -> None:
    loaded: list[str] = []

    class _Processor:
        @classmethod
        def from_pretrained(cls, name: str) -> Any:
            loaded.append("processor")
            return object()

    class _Model:
        @classmethod
        def from_pretrained(cls, name: str) -> Any:
            loaded.append("model")
            return object()

    with patch.object(mm, "_CLIP_AVAILABLE", True), patch.object(mm, "CLIPProcessor", _Processor), patch.object(
        mm, "CLIPModel", _Model
    ):
        rag = mm.MultiModalRAG(dimension=32)
        rag.set_index_path(tmp_path / "idx.json")
        assert loaded == [], "constructing the engine already loaded a vision model"
        assert rag.search("hello", top_k=2, include_images=False) == []
        assert loaded == [], "a text-only search paid for CLIP"
        assert rag._clip_ready() is True
        assert loaded == ["processor", "model"], "the image path must still load it on demand"
