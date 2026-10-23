"""VectorStore integrity: filtered top-k, deferred index rebuild, atomic and crash-safe persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from raven.core.rag.vector_store import VectorStore


class DirectionalEngine:
    """Embeds 'b…' texts toward dimension 0 and everything else toward dimension 1."""

    dim = 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.02, 0.0, 0.0] if t.startswith("b") else [0.02, 1.0, 0.0, 0.0] for t in texts]


@pytest.fixture
def store(tmp_path: Path) -> VectorStore:
    return VectorStore(tmp_path / "vectors", DirectionalEngine())  # type: ignore[arg-type]


async def _seed(store: VectorStore) -> None:
    for i in range(6):
        await store.upsert(f"b{i}", f"b text {i}", {"space": "b"})
    for i in range(6):
        await store.upsert(f"a{i}", f"a text {i}", {"space": "a"})


class TestFilteredTopK:
    async def test_matching_docs_below_the_cut_are_still_returned(self, store: VectorStore) -> None:
        await _seed(store)
        results = await store.search("b0 text", k=5, filter_meta={"space": "a"})
        assert len(results) == 5, f"filtered semantic search truncated to {len(results)} of 5"
        assert {r["id"] for r in results} == {f"a{i}" for i in range(5)}

    async def test_every_returned_doc_satisfies_the_filter(self, store: VectorStore) -> None:
        await _seed(store)
        results = await store.search("b0 text", k=12, filter_meta={"space": "a"})
        assert len(results) == 6
        assert all(r["metadata"]["space"] == "a" for r in results)

    async def test_semantic_and_lexical_agree_on_the_filtered_count(self, store: VectorStore) -> None:
        await _seed(store)
        sem = await store.search("b0 text", k=5, filter_meta={"space": "a"})
        lex = await store.search("a text", k=5, filter_meta={"space": "a"})
        hyb = await store.search("b0 text", k=5, filter_meta={"space": "a"}, search_mode="hybrid")
        assert len(sem) == len(lex) == len(hyb) == 5

    async def test_semantic_scores_survive_the_shared_ranker(self, store: VectorStore) -> None:
        await _seed(store)
        results = await store.search("b0 text", k=3, filter_meta={"space": "a"})
        assert all(r["score"] == pytest.approx(r["scores"]["semantic"]) for r in results)
        assert all(r["scores"]["lexical"] == 0.0 for r in results)

    async def test_unfiltered_search_still_respects_k(self, store: VectorStore) -> None:
        await _seed(store)
        assert len(await store.search("b0 text", k=4)) == 4


class TestIndexRebuildIsDeferred:
    async def test_ingest_rebuilds_once_on_the_next_search(
        self, store: VectorStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        real = store._rebuild_index

        def counted() -> None:
            calls.append("rebuild")
            real()

        monkeypatch.setattr(store, "_rebuild_index", counted)
        for i in range(20):
            await store.upsert(f"doc{i}", f"body {i}", {})
        assert calls == [], f"per-document rebuild is back: {len(calls)} rebuilds"
        await store.search("body 1", k=3)
        assert calls == ["rebuild"]

    async def test_a_mutation_after_a_search_invalidates_again(
        self, store: VectorStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        real = store._rebuild_index
        monkeypatch.setattr(store, "_rebuild_index", lambda: (calls.append("r"), real())[1])
        await store.upsert("a", "alpha")
        await store.search("alpha", k=1)
        await store.upsert("b", "beta")
        assert store._index_stale is True
        await store.search("beta", k=1)
        assert len(calls) == 2


class TestCrashSafePersistence:
    async def test_torn_vectors_file_is_parked_and_never_recycled(
        self, store: VectorStore, tmp_path: Path
    ) -> None:
        await store.upsert("keep", "important text", {"n": 1})
        path = tmp_path / "vectors" / "vectors.json"
        path.write_text(path.read_text(encoding="utf-8")[:40], encoding="utf-8")

        reloaded = VectorStore(tmp_path / "vectors", DirectionalEngine())  # type: ignore[arg-type]
        parked = list((tmp_path / "vectors").glob("vectors.json.corrupt-*"))
        assert parked, "an unreadable store was recycled instead of parked"
        assert not path.exists()
        assert reloaded.count() == 0

        await reloaded.upsert("fresh", "new text", {"n": 2})
        assert len(list((tmp_path / "vectors").glob("vectors.json.corrupt-*"))) == 1
        assert json.loads(path.read_text(encoding="utf-8")) == {"fresh": reloaded._vectors["fresh"]}

    async def test_no_temp_file_survives_a_write(self, store: VectorStore, tmp_path: Path) -> None:
        await store.upsert("a", "alpha", {})
        assert list((tmp_path / "vectors").glob("*.tmp")) == []

    async def test_concurrent_upserts_leave_a_consistent_store(self, store: VectorStore, tmp_path: Path) -> None:
        await asyncio.gather(*[store.upsert(f"c{i}", f"concurrent body {i}", {"n": i}) for i in range(12)])
        vectors = json.loads((tmp_path / "vectors" / "vectors.json").read_text(encoding="utf-8"))
        metadata = json.loads((tmp_path / "vectors" / "metadata.json").read_text(encoding="utf-8"))
        assert len(vectors) == len(metadata) == store.count() == 12
        assert list((tmp_path / "vectors").glob("*.tmp")) == []
        assert len(await store.search("concurrent body", k=5)) == 5

    async def test_metadata_and_vectors_never_disagree_after_a_mutating_failure(
        self, store: VectorStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await store.upsert("a", "alpha", {"n": 1})
        real_dumps = json.dumps

        def boom(obj: Any, **kw: Any) -> str:
            if isinstance(obj, dict) and "a" in obj:
                raise OSError("disk full")
            return real_dumps(obj, **kw)

        # The previous vectors file must still be intact: a failed write may not truncate it.
        with monkeypatch.context() as m:
            m.setattr(json, "dumps", boom)
            with pytest.raises(OSError):
                await store.upsert("b", "beta", {"n": 2})
            assert json.loads((tmp_path / "vectors" / "vectors.json").read_text(encoding="utf-8")) == {
                "a": store._vectors["a"]
            }

