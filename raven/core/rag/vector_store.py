from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from raven.core.rag.bm25 import BM25Index
from raven.core.rag.embeddings import EmbeddingEngine

_VECTORS_PATH = "vectors.json"


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]

try:
    import hnswlib

    HAS_HNSW = True
except ImportError:
    HAS_HNSW = False


class VectorStore:
    def __init__(self, db_path: Path | str, embedding_engine: EmbeddingEngine | None = None, dim: int = 384):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.engine = embedding_engine or EmbeddingEngine(provider="local")
        self._dim = dim
        self._vectors: dict[str, list[float]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._index: Any = None
        self._id_map: dict[int, str] = {}
        self._next_label: int = 0
        self._load()
        self._init_index()

    def _init_index(self) -> None:
        self._index = None
        if HAS_HNSW and len(self._vectors) > 0:
            try:
                idx = hnswlib.Index(space="cosine", dim=self._dim)
                idx.init_index(max_elements=max(len(self._vectors) * 2, 1000), ef_construction=200, M=16)
                labels = []
                data = []
                for label, (doc_id, vec) in enumerate(self._vectors.items()):
                    labels.append(label)
                    data.append(vec)
                    self._id_map[label] = doc_id
                    self._next_label = label + 1
                idx.add_items(np.array(data, dtype=np.float32), np.array(labels))
                idx.set_ef(50)
                self._index = idx
            except Exception as e:
                logger.warning("HNSW init failed, falling back to brute force: {}", e)
                self._index = None

    def _vectors_path(self) -> Path:
        return self.db_path / _VECTORS_PATH

    def _metadata_path(self) -> Path:
        return self.db_path / "metadata.json"

    def _load(self):
        vpath = self._vectors_path()
        if vpath.exists():
            try:
                with vpath.open() as f:
                    raw = json.load(f)
                    self._vectors = {k: list(v) if isinstance(v, list) else [] for k, v in raw.items()}
            except Exception as e:
                logger.warning("Failed to load vectors: {}", e)
        mpath = self._metadata_path()
        if mpath.exists():
            try:
                with mpath.open() as f:
                    raw = json.load(f)
                    self._metadata = {k: v for k, v in raw.items()}
            except Exception as e:
                logger.warning("Failed to load metadata: {}", e)

    def _as_np(self, vec: list[float]) -> np.ndarray:
        return np.array(vec, dtype=np.float32)

    def _save(self):
        def _to_plain(v: Any) -> Any:
            if isinstance(v, np.ndarray):
                return v.tolist()
            if isinstance(v, (np.floating, np.integer)):
                return v.item()
            if isinstance(v, list):
                return [_to_plain(x) for x in v]
            return v

        serializable = {k: _to_plain(v) for k, v in self._vectors.items()}
        with self._vectors_path().open("w") as f:
            json.dump(serializable, f)
        with self._metadata_path().open("w") as f:
            json.dump(self._metadata, f, default=str)

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None):
        vecs = await self.engine.embed([text])
        self._vectors[doc_id] = list(self._as_np(vecs[0]))
        self._metadata[doc_id] = {
            "text": text[:1000],
            "full_text": text,
            "timestamp": time.time(),
            **(metadata or {}),
        }
        await asyncio.to_thread(self._save)
        await asyncio.to_thread(self._rebuild_index)

    async def upsert_batch(self, items: list[tuple[str, str, dict[str, Any] | None]]):
        texts = [item[1] for item in items]
        vecs = await self.engine.embed(texts)
        for i, (doc_id, text, meta) in enumerate(items):
            self._vectors[doc_id] = list(self._as_np(vecs[i]))
            self._metadata[doc_id] = {
                "text": text[:1000],
                "full_text": text,
                "timestamp": time.time(),
                **(meta or {}),
            }
        await asyncio.to_thread(self._save)
        await asyncio.to_thread(self._rebuild_index)

    def _rebuild_index(self) -> None:
        if not HAS_HNSW or len(self._vectors) < 10:
            self._index = None
            return
        try:
            idx = hnswlib.Index(space="cosine", dim=self._dim)
            idx.init_index(max_elements=max(len(self._vectors) * 2, 1000), ef_construction=200, M=16)
            labels = []
            data = []
            self._id_map.clear()
            for label, (doc_id, vec) in enumerate(self._vectors.items()):
                labels.append(label)
                data.append(vec)
                self._id_map[label] = doc_id
                self._next_label = label + 1
            idx.add_items(np.array(data, dtype=np.float32), np.array(labels))
            idx.set_ef(50)
            self._index = idx
        except Exception as e:
            logger.warning("HNSW rebuild failed: {}", e)
            self._index = None

    async def delete(self, doc_id: str):
        self._vectors.pop(doc_id, None)
        self._metadata.pop(doc_id, None)
        await asyncio.to_thread(self._save)
        await asyncio.to_thread(self._rebuild_index)

    async def search(
        self,
        query: str,
        k: int = 5,
        filter_meta: dict[str, Any] | None = None,
        search_mode: str = "semantic",
        alpha: float = 0.7,
    ) -> list[dict[str, Any]]:
        if not self._vectors:
            return []
        if search_mode == "lexical":
            return self._search_lexical(query, k=k, filter_meta=filter_meta)
        if search_mode == "hybrid":
            return await self._search_hybrid(query, k=k, filter_meta=filter_meta, alpha=alpha)
        return await self._search_semantic(query, k=k, filter_meta=filter_meta)

    async def _search_semantic(
        self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        query_vecs = await self.engine.embed([query])
        query_vec = self._as_np(query_vecs[0])

        if self._index is not None:
            labels, distances = self._index.knn_query(np.array([query_vec]), k=min(k, len(self._vectors)))
            results = []
            for label, dist in zip(labels[0], distances[0], strict=True):
                doc_id = self._id_map.get(label, "")
                meta = self._metadata.get(doc_id, {})
                if filter_meta and not all(meta.get(ck) == cv for ck, cv in filter_meta.items()):
                    continue
                results.append(
                    {
                        "id": doc_id,
                        "text": meta.get("full_text") or meta.get("text", ""),
                        "score": float(1.0 - dist),
                        "metadata": meta,
                        "scores": {"semantic": float(1.0 - dist), "lexical": 0.0},
                    }
                )
            return results

        ids = list(self._vectors.keys())
        mat = np.array([self._as_np(self._vectors[i]) for i in ids])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        sims = (mat @ query_vec) / (norms + 1e-10)
        top_k = min(k, len(ids))
        top_idx = sorted(range(len(ids)), key=lambda i: (-float(sims[i]), i))[:top_k]
        results = []
        for idx in top_idx:
            doc_id = ids[idx]
            meta = self._metadata.get(doc_id, {})
            if filter_meta and not all(meta.get(ck) == cv for ck, cv in filter_meta.items()):
                continue
            results.append(
                {
                    "id": doc_id,
                    "text": meta.get("full_text") or meta.get("text", ""),
                    "score": float(sims[idx]),
                    "metadata": meta,
                    "scores": {"semantic": float(sims[idx]), "lexical": 0.0},
                }
            )
        return results

    def _search_lexical(
        self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        doc_ids = list(self._vectors.keys())
        texts = [self._metadata.get(d, {}).get("text", "") for d in doc_ids]
        bm25 = BM25Index().fit(texts)
        lex = bm25.scores(query)
        return self._rank_results(doc_ids, texts, lex, "lexical", filter_meta, k, semantic_scores=None)

    async def _search_hybrid(
        self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None, alpha: float = 0.7
    ) -> list[dict[str, Any]]:
        doc_ids = list(self._vectors.keys())
        texts = [self._metadata.get(d, {}).get("text", "") for d in doc_ids]
        query_vecs = await self.engine.embed([query])
        query_vec = self._as_np(query_vecs[0])
        mat = np.array([self._as_np(self._vectors[i]) for i in doc_ids])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        sem = ((mat @ query_vec) / (norms + 1e-10)).tolist()
        bm25 = BM25Index().fit(texts)
        lex = bm25.scores(query)
        sem_n = _normalize(sem)
        lex_n = _normalize(lex)
        fused = [alpha * s + (1.0 - alpha) * lex_v for s, lex_v in zip(sem_n, lex_n, strict=True)]
        return self._rank_results(doc_ids, texts, fused, "hybrid", filter_meta, k, semantic_scores=sem)

    def _rank_results(
        self,
        doc_ids: list[str],
        texts: list[str],
        scores: list[float],
        mode: str,
        filter_meta: dict[str, Any] | None,
        k: int,
        semantic_scores: list[float] | None,
    ) -> list[dict[str, Any]]:
        order = sorted(range(len(doc_ids)), key=lambda i: scores[i], reverse=True)
        results: list[dict[str, Any]] = []
        for idx in order:
            doc_id = doc_ids[idx]
            meta = self._metadata.get(doc_id, {})
            if filter_meta and not all(meta.get(ck) == cv for ck, cv in filter_meta.items()):
                continue
            entry: dict[str, Any] = {
                "id": doc_id,
                "text": meta.get("full_text") or texts[idx],
                "score": float(scores[idx]),
                "metadata": meta,
                "scores": {"semantic": float(semantic_scores[idx]) if semantic_scores else 0.0, "lexical": 0.0},
            }
            if mode == "lexical":
                entry["scores"]["lexical"] = float(scores[idx])
            results.append(entry)
            if len(results) >= k:
                break
        return results

    def count(self) -> int:
        return len(self._vectors)

    def list_ids(self) -> list[str]:
        return list(self._vectors.keys())

    def get_metadata(self, doc_id: str) -> dict[str, Any] | None:
        return self._metadata.get(doc_id)

    async def clear(self):
        self._vectors.clear()
        self._metadata.clear()
        await asyncio.to_thread(self._save)
