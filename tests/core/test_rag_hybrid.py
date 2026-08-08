from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.rag.bm25 import BM25Index, tokenize
from raven.core.rag.embeddings import EmbeddingEngine
from raven.core.rag.vector_store import VectorStore


class ConstantEmbeddingEngine:
    """All texts map to the same vector — semantic similarity carries no signal."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "vectors"


class TestBM25:
    def test_tokenize_lowercases(self):
        assert tokenize("Hello, WORLD_2!") == ["hello", "world_2"]

    def test_exact_term_ranks_higher(self):
        bm = BM25Index().fit(
            ["the quick brown fox", "completely unrelated text", "quick fox again"]
        )
        scores = bm.scores("quick fox")
        assert scores[0] > scores[1]
        assert scores[2] > scores[1]

    def test_no_match_zero(self):
        bm = BM25Index().fit(["alpha beta", "gamma"])
        scores = bm.scores("zzz")
        assert scores == [0.0, 0.0]

    def test_empty_query(self):
        bm = BM25Index().fit(["alpha"])
        assert bm.scores("") == [0.0]

    def test_unknown_term_idf(self):
        bm = BM25Index().fit(["rare", "rare rare"])
        scores = bm.scores("rare")
        assert scores[1] > scores[0]

    def test_not_fitted(self):
        assert BM25Index().scores("q") == []


class TestHybridSearch:
    async def test_hybrid_ranks_exact_term_first(self, tmp_db: Path):
        vs = VectorStore(tmp_db, ConstantEmbeddingEngine(), dim=4)  # type: ignore[arg-type]
        await vs.upsert("plants", "unrelated content about plants", {"source": "a"})
        await vs.upsert("answer", "the answer is 42", {"source": "b"})

        semantic = await vs.search("42", k=5, search_mode="semantic")
        assert semantic[0]["id"] == "plants"

        hybrid = await vs.search("42", k=5, search_mode="hybrid")
        assert hybrid[0]["id"] == "answer"

    async def test_lexical_mode(self, tmp_db: Path):
        vs = VectorStore(tmp_db, ConstantEmbeddingEngine(), dim=4)  # type: ignore[arg-type]
        await vs.upsert("a", "alpha beta gamma", {"g": 1})
        await vs.upsert("b", "delta", {"g": 2})
        results = await vs.search("beta", k=5, search_mode="lexical")
        assert results[0]["id"] == "a"
        assert results[0]["scores"]["lexical"] > 0.0

    async def test_hybrid_includes_scores(self, tmp_db: Path):
        vs = VectorStore(tmp_db, ConstantEmbeddingEngine(), dim=4)  # type: ignore[arg-type]
        await vs.upsert("a", "shared term here")
        await vs.upsert("b", "shared term too")
        results = await vs.search("shared term", k=2, search_mode="hybrid")
        for r in results:
            assert "semantic" in r["scores"]
            assert "lexical" in r["scores"]

    async def test_hybrid_respects_filter(self, tmp_db: Path):
        vs = VectorStore(tmp_db, ConstantEmbeddingEngine(), dim=4)  # type: ignore[arg-type]
        await vs.upsert("a", "target keyword", {"group": "one"})
        await vs.upsert("b", "target keyword", {"group": "two"})
        results = await vs.search("target", k=5, search_mode="hybrid", filter_meta={"group": "one"})
        assert len(results) == 1
        assert results[0]["id"] == "a"

    async def test_retriever_defaults_to_hybrid(self, tmp_db: Path):
        from raven.core.rag.retriever import Retriever

        r = Retriever(db_path=str(tmp_db), engine=ConstantEmbeddingEngine())  # type: ignore[arg-type]
        await r.index_text("a", "the answer is 42", {"source": "s"})
        await r.index_text("b", "unrelated plants", {})
        results = await r.retrieve("42", k=2)
        assert results[0]["id"] == "a"
        assert "scores" in results[0]


class TestEmbeddingCache:
    @pytest.fixture
    def cache_file(self, tmp_path: Path) -> Path:
        return tmp_path / "cache" / "embeddings_cache.json"

    @staticmethod
    def _patched_engine(cache_file: Path) -> tuple[EmbeddingEngine, AsyncMock]:
        engine = EmbeddingEngine(provider="local", cache_path=cache_file)
        mock = AsyncMock(side_effect=lambda texts: [[0.0, 1.0, 2.0] for _ in texts])
        engine._embed_local = mock  # type: ignore[method-assign]
        return engine, mock

    async def test_cache_hit_avoids_recompute(self, cache_file: Path):
        engine, mock = self._patched_engine(cache_file)
        await engine.embed(["alpha"])
        await engine.embed(["alpha"])
        assert mock.call_count == 1

    async def test_cache_persists_across_instances(self, cache_file: Path):
        engine_a, _ = self._patched_engine(cache_file)
        await engine_a.embed(["persisted text"])

        engine_b, mock_b = self._patched_engine(cache_file)
        result = await engine_b.embed(["persisted text"])
        assert mock_b.call_count == 0
        assert result == [[0.0, 1.0, 2.0]]

    async def test_clear_cache(self, cache_file: Path):
        engine, mock = self._patched_engine(cache_file)
        await engine.embed(["x"])
        engine.clear_cache()
        await engine.embed(["x"])
        assert mock.call_count == 2
