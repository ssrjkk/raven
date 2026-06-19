from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from raven.core.rag.embeddings import EmbeddingEngine

_VECTORS_PATH = "vectors.json"


class VectorStore:
    def __init__(self, db_path: Path | str, embedding_engine: EmbeddingEngine | None = None):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.engine = embedding_engine or EmbeddingEngine(provider="local")
        self._vectors: dict[str, list[float]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._load()

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
        serializable = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in self._vectors.items()}
        with self._vectors_path().open("w") as f:
            json.dump(serializable, f)
        with self._metadata_path().open("w") as f:
            json.dump(self._metadata, f, default=str)

    async def upsert(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None):
        vecs = await self.engine.embed([text])
        self._vectors[doc_id] = list(self._as_np(vecs[0]))
        self._metadata[doc_id] = {
            "text": text[:1000],
            "timestamp": time.time(),
            **(metadata or {}),
        }
        self._save()

    async def upsert_batch(self, items: list[tuple[str, str, dict[str, Any] | None]]):
        texts = [item[1] for item in items]
        vecs = await self.engine.embed(texts)
        for i, (doc_id, text, meta) in enumerate(items):
            self._vectors[doc_id] = list(self._as_np(vecs[i]))
            self._metadata[doc_id] = {
                "text": text[:1000],
                "timestamp": time.time(),
                **(meta or {}),
            }
        self._save()

    def delete(self, doc_id: str):
        self._vectors.pop(doc_id, None)
        self._metadata.pop(doc_id, None)
        self._save()

    async def search(self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self._vectors:
            return []
        query_vecs = await self.engine.embed([query])
        query_vec = self._as_np(query_vecs[0])
        ids = list(self._vectors.keys())
        mat = np.array([self._as_np(self._vectors[i]) for i in ids])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        sims = (mat @ query_vec) / (norms + 1e-10)
        top_k = min(k, len(ids))
        top_idx = np.argsort(sims)[::-1][:top_k]
        results = []
        for idx in top_idx:
            doc_id = ids[idx]
            meta = self._metadata.get(doc_id, {})
            if filter_meta and not all(meta.get(k) == v for k, v in filter_meta.items()):
                    continue
            results.append(
                {
                    "id": doc_id,
                    "text": meta.get("text", ""),
                    "score": float(sims[idx]),
                    "metadata": meta,
                }
            )
        return results

    def count(self) -> int:
        return len(self._vectors)

    def list_ids(self) -> list[str]:
        return list(self._vectors.keys())

    def get_metadata(self, doc_id: str) -> dict[str, Any] | None:
        return self._metadata.get(doc_id)

    def clear(self):
        self._vectors.clear()
        self._metadata.clear()
        self._save()
