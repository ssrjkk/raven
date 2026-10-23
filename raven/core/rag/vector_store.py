from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from raven.core.rag.bm25 import BM25Index
from raven.core.rag.embeddings import EmbeddingEngine

_VECTORS_PATH = "vectors.json"
_MIN_HNSW_DOCS = 10


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
        self._bm25_cache: Any = None
        self._bm25_texts: list[str] = []
        self._bm25_ids: list[str] = []
        # The HNSW index and the JSON files are rewritten from worker threads; without these the
        # threads interleave inside the same file and the label->doc_id map goes out of sync.
        self._write_lock = threading.Lock()
        self._mutate_lock = asyncio.Lock()
        self._index_stale = False
        self._load()
        self._init_index()

    def _init_index(self) -> None:
        # One rule for every path: below _MIN_HNSW_DOCS exact brute force beats an approximate
        # index, and the previous >0 here vs >=10 in the rebuild meant a store changed its own
        # matching behaviour after the first upsert.
        self._index = None
        if HAS_HNSW and len(self._vectors) >= _MIN_HNSW_DOCS:
            with self._write_lock:
                self._build_index_locked()

    def _vectors_path(self) -> Path:
        return self.db_path / _VECTORS_PATH

    def _metadata_path(self) -> Path:
        return self.db_path / "metadata.json"

    def _load(self):
        vpath = self._vectors_path()
        if vpath.exists():
            try:
                with vpath.open(encoding="utf-8") as f:
                    raw = json.load(f)
                    self._vectors = {k: list(v) if isinstance(v, list) else [] for k, v in raw.items()}
            except Exception as e:
                # A store that fails to parse reads as empty, and the next save would then write
                # the empty set over it. Park the unreadable file instead of recycling its name.
                logger.error("Failed to load {}: {} - parking it as {}", vpath, e, self._park(vpath))
        mpath = self._metadata_path()
        if mpath.exists():
            try:
                with mpath.open(encoding="utf-8") as f:
                    raw = json.load(f)
                    self._metadata = {k: v for k, v in raw.items()}
            except Exception as e:
                logger.error("Failed to load {}: {} - parking it as {}", mpath, e, self._park(mpath))

    def _park(self, path: Path) -> Path:
        moved = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(moved)
        except OSError as exc:
            logger.error("Could not park unreadable {}: {}", path, exc)
            return path
        return moved

    def _atomic_write(self, path: Path, payload: str) -> None:
        tmp = path.with_name(f"{path.name}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

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

        with self._write_lock:
            self._bm25_cache = None
            self._atomic_write(self._vectors_path(), json.dumps({k: _to_plain(v) for k, v in self._vectors.items()}))
            self._atomic_write(self._metadata_path(), json.dumps(self._metadata, default=str, ensure_ascii=False))

    def _rebuild_index(self) -> None:
        """Rebuild now. Callers normally only set _index_stale; ingest does not need a rebuild per doc."""
        with self._write_lock:
            self._build_index_locked()
            self._index_stale = False

    def _build_index_locked(self) -> None:
        if not HAS_HNSW or len(self._vectors) < _MIN_HNSW_DOCS:
            self._index = None
            return
        try:
            idx = hnswlib.Index(space="cosine", dim=self._dim)
            idx.init_index(max_elements=max(len(self._vectors) * 2, 1000), ef_construction=200, M=16)
            labels = []
            data = []
            id_map: dict[int, str] = {}
            for label, (doc_id, vec) in enumerate(self._vectors.items()):
                labels.append(label)
                data.append(vec)
                id_map[label] = doc_id
            idx.add_items(np.array(data, dtype=np.float32), np.array(labels))
            idx.set_ef(50)
            self._id_map = id_map
            self._next_label = len(labels)
            self._index = idx
        except Exception as e:
            logger.warning("HNSW rebuild failed: {}", e)
            self._index = None

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None):
        vecs = await self.engine.embed([text])
        async with self._mutate_lock:
            self._vectors[doc_id] = list(self._as_np(vecs[0]))
            self._metadata[doc_id] = {
                "text": text[:1000],
                "full_text": text,
                "timestamp": time.time(),
                **(metadata or {}),
            }
            await self._persist()

    async def upsert_batch(self, items: list[tuple[str, str, dict[str, Any] | None]]):
        texts = [item[1] for item in items]
        vecs = await self.engine.embed(texts)
        async with self._mutate_lock:
            for i, (doc_id, text, meta) in enumerate(items):
                self._vectors[doc_id] = list(self._as_np(vecs[i]))
                self._metadata[doc_id] = {
                    "text": text[:1000],
                    "full_text": text,
                    "timestamp": time.time(),
                    **(meta or {}),
                }
            await self._persist()

    async def _persist(self) -> None:
        """Write the store once and defer the index rebuild to the next search.

        Rebuilding (and rewriting both JSON files) per document made an N-document ingest O(N^2):
        ingest of 5k docs rewrote the whole vectors.json 5k times.
        """
        self._bm25_cache = None
        self._index_stale = True
        await asyncio.to_thread(self._save)

    async def delete(self, doc_id: str):
        async with self._mutate_lock:
            self._vectors.pop(doc_id, None)
            self._metadata.pop(doc_id, None)
            await self._persist()

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

        ids = list(self._vectors.keys())
        if not ids:
            return []

        # A metadata filter has to be exact: taking the approximate top-k first and dropping the
        # non-matching entries afterwards returned fewer than k - and with the matching documents
        # sitting below the cut, it returned nothing at all while lexical/hybrid found five.
        if not filter_meta:
            if self._index_stale:
                await asyncio.to_thread(self._rebuild_index)
            if self._index is not None:
                labels, distances = self._index.knn_query(np.array([query_vec]), k=min(k, len(ids)))
                results = []
                for label, dist in zip(labels[0], distances[0], strict=True):
                    doc_id = self._id_map.get(label, "")
                    meta = self._metadata.get(doc_id, {})
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

        return self._exact_semantic(ids, query_vec, k, filter_meta)

    def _exact_semantic(
        self, ids: list[str], query_vec: np.ndarray, k: int, filter_meta: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        mat = np.array([self._as_np(self._vectors[i]) for i in ids])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        sims = ((mat @ query_vec) / (norms + 1e-10)).tolist()
        texts = [self._metadata.get(d, {}).get("text", "") for d in ids]
        return self._rank_results(ids, texts, sims, "semantic", filter_meta, k, semantic_scores=sims)

    def _get_bm25(self) -> tuple[Any, list[str], list[str]]:
        doc_ids = list(self._vectors.keys())
        texts = [self._metadata.get(d, {}).get("text", "") for d in doc_ids]
        if self._bm25_cache is None or self._bm25_ids != doc_ids:
            self._bm25_cache = BM25Index().fit(texts)
            self._bm25_ids = doc_ids
            self._bm25_texts = texts
        return self._bm25_cache, doc_ids, texts

    def _search_lexical(
        self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        bm25, doc_ids, texts = self._get_bm25()
        lex = bm25.scores(query)
        return self._rank_results(doc_ids, texts, lex, "lexical", filter_meta, k, semantic_scores=None)

    async def _search_hybrid(
        self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None, alpha: float = 0.7
    ) -> list[dict[str, Any]]:
        bm25, doc_ids, texts = self._get_bm25()
        query_vecs = await self.engine.embed([query])
        query_vec = self._as_np(query_vecs[0])
        mat = np.array([self._as_np(self._vectors[i]) for i in doc_ids])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        sem = ((mat @ query_vec) / (norms + 1e-10)).tolist()
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
        async with self._mutate_lock:
            self._vectors.clear()
            self._metadata.clear()
            await self._persist()
