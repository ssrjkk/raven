from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.rag.vector_store import VectorStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "vectors"


class FakeEmbeddingEngine:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


@pytest.fixture
def vs(tmp_db: Path) -> VectorStore:
    return VectorStore(tmp_db, FakeEmbeddingEngine())  # type: ignore[arg-type]


class TestVectorStore:
    async def test_empty_store(self, vs: VectorStore):
        assert vs.count() == 0
        assert vs.list_ids() == []
        assert await vs.search("hello") == []

    async def test_upsert_and_count(self, vs: VectorStore):
        await vs.upsert("doc1", "hello world", {"source": "test"})
        assert vs.count() == 1
        assert vs.list_ids() == ["doc1"]
        meta = vs.get_metadata("doc1")
        assert meta is not None
        assert meta["text"] == "hello world"
        assert meta["source"] == "test"

    async def test_search_returns_results(self, vs: VectorStore):
        await vs.upsert("a", "alpha")
        await vs.upsert("b", "beta")
        results = await vs.search("query", k=5)
        assert len(results) == 2
        assert all("id" in r and "text" in r and "score" in r and "metadata" in r for r in results)

    async def test_search_respects_k(self, vs: VectorStore):
        for i in range(10):
            await vs.upsert(f"doc{i}", f"text {i}")
        results = await vs.search("query", k=3)
        assert len(results) == 3

    async def test_search_with_filter(self, vs: VectorStore):
        await vs.upsert("a", "apple", {"group": "fruit"})
        await vs.upsert("b", "broccoli", {"group": "veg"})
        results = await vs.search("food", k=5, filter_meta={"group": "fruit"})
        assert len(results) == 1
        assert results[0]["id"] == "a"

    async def test_delete(self, vs: VectorStore):
        await vs.upsert("keep", "keep me")
        await vs.upsert("gone", "delete me")
        assert vs.count() == 2
        await vs.delete("gone")
        assert vs.count() == 1
        assert vs.list_ids() == ["keep"]

    async def test_clear(self, vs: VectorStore):
        await vs.upsert("a", "alpha")
        await vs.upsert("b", "beta")
        await vs.clear()
        assert vs.count() == 0

    async def test_upsert_batch(self, vs: VectorStore):
        items = [("x", "ex", {"n": 1}), ("y", "why", {"n": 2})]
        await vs.upsert_batch(items)  # type: ignore[arg-type]
        assert vs.count() == 2
        assert vs.get_metadata("x") is not None
        assert vs.get_metadata("y") is not None

    async def test_persistence(self, tmp_db: Path):
        eng = FakeEmbeddingEngine()
        vs = VectorStore(tmp_db, eng)  # type: ignore[arg-type]
        await vs.upsert("persist", "hello", {"k": "v"})
        assert vs.count() == 1
        vs2 = VectorStore(tmp_db, eng)  # type: ignore[arg-type]
        assert vs2.count() == 1
        assert vs2.get_metadata("persist") is not None
        await vs2.delete("persist")
        vs3 = VectorStore(tmp_db, eng)  # type: ignore[arg-type]
        assert vs3.count() == 0

    async def test_get_metadata_missing(self, vs: VectorStore):
        assert vs.get_metadata("nonexistent") is None

    async def test_delete_nonexistent(self, vs: VectorStore):
        await vs.delete("does_not_exist")
        assert vs.count() == 0


async def test_retriever_index_and_retrieve(tmp_db: Path):
    from raven.core.rag.retriever import Retriever

    r = Retriever(db_path=str(tmp_db), engine=FakeEmbeddingEngine())  # type: ignore[arg-type]
    await r.index_text("test1", "hello there", {"source": "greeting"})
    assert r.count() == 1
    results = await r.retrieve("hello", k=5)
    assert len(results) >= 1
    assert results[0]["id"] == "test1"

async def test_retriever_context(tmp_db: Path):
    from raven.core.rag.retriever import Retriever

    r = Retriever(db_path=str(tmp_db), engine=FakeEmbeddingEngine())  # type: ignore[arg-type]
    await r.index_text("a", "alpha")
    await r.index_text("b", "beta")
    ctx = await r.retrieve_context("alpha", k=5)
    assert "alpha" in ctx
    assert "beta" in ctx

async def test_retriever_index_chunks(tmp_db: Path):
    chunks = [
        {"text": "chunk one", "page": 1},
        {"text": "chunk two", "page": 2},
    ]
    from raven.core.rag.retriever import Retriever

    r = Retriever(db_path=str(tmp_db), engine=FakeEmbeddingEngine())  # type: ignore[arg-type]
    await r.index_chunks(chunks, prefix="doc")
    assert r.count() == 2
    results = await r.retrieve("test", k=5)
    assert len(results) == 2


def test_rag_api_metrics(tmp_path: Path):
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from raven.core.metrics import metrics
    from raven.core.rag_api import create_rag_router

    metrics.clear()
    with patch("raven.core.rag_api._RAG_PATH", tmp_path / "rag_index.json"):
        app = FastAPI()
        app.include_router(create_rag_router())
        with TestClient(app) as client:
            resp = client.post("/api/rag/index", json={"document_id": "d1", "text": "hello world"})
            assert resp.status_code == 200
            assert resp.json()["chunks"] >= 1
            resp = client.post(
                "/api/rag/search", json={"query": "hello", "top_k": 2, "include_images": False}
            )
            assert resp.status_code == 200
    snap = metrics.snapshot()
    assert snap.get("raven_rag_index_document_total") == 1
    assert snap.get("raven_rag_index_count", 0) >= 1
    assert snap.get("raven_rag_search_count", 0) >= 1
