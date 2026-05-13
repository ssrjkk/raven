from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.rag.embeddings import EmbeddingEngine
from raven.core.rag.vector_store import VectorStore


class Retriever:
    def __init__(self, vector_store: VectorStore | None = None, engine: EmbeddingEngine | None = None, db_path: str = "data/rag"):
        if vector_store:
            self.store = vector_store
        else:
            eng = engine or EmbeddingEngine(provider="local")
            from pathlib import Path
            self.store = VectorStore(Path(db_path), eng)

    async def index_text(self, doc_id: str, text: str, metadata: dict | None = None):
        await self.store.upsert(doc_id, text, metadata)

    async def index_chunks(self, chunks: list[dict[str, Any]], prefix: str = ""):
        items = []
        for i, chunk in enumerate(chunks):
            doc_id = f"{prefix}:{i}" if prefix else str(i)
            text = chunk["text"]
            meta = {k: v for k, v in chunk.items() if k != "text"}
            items.append((doc_id, text, meta))
        if items:
            await self.store.upsert_batch(items)
            logger.info("Indexed {} chunks ({})", len(items), prefix or "root")

    async def retrieve(self, query: str, k: int = 5, filter_meta: dict | None = None) -> list[dict[str, Any]]:
        return await self.store.search(query, k=k, filter_meta=filter_meta)

    async def retrieve_context(self, query: str, k: int = 5, max_tokens: int = 3000) -> str:
        results = await self.retrieve(query, k=k)
        if not results:
            return ""
        parts = []
        total = 0
        for r in results:
            text = r["text"]
            if total + len(text) > max_tokens:
                text = text[: max_tokens - total]
            source = r["metadata"].get("source", r["id"])
            parts.append(f"[Source: {source}]\n{text}")
            total += len(text)
            if total >= max_tokens:
                break
        return "\n\n---\n\n".join(parts)

    def count(self) -> int:
        return self.store.count()

    def clear(self):
        self.store.clear()
