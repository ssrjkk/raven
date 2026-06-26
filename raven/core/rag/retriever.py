from __future__ import annotations

import re
from typing import Any

from loguru import logger

from raven.core.rag.embeddings import EmbeddingEngine
from raven.core.rag.vector_store import VectorStore


def _semantic_chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[dict[str, Any]]:
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[dict[str, Any]] = []
    buffer = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if buffer and len(buffer) + len(para) > max_chars:
            chunks.append({"text": buffer.strip(), "type": "text"})
            buffer = para
        else:
            buffer = (buffer + "\n\n" + para) if buffer else para
    if buffer:
        chunks.append({"text": buffer.strip(), "type": "text"})
    if overlap > 0 and len(chunks) > 1:
        merged = []
        for i, c in enumerate(chunks):
            merged.append(c)
            if i < len(chunks) - 1:
                next_start = chunks[i + 1]["text"][:overlap]
                merged.append({"text": next_start, "type": "overlap"})
        chunks = merged
    return chunks


class Retriever:
    def __init__(
        self, vector_store: VectorStore | None = None, engine: EmbeddingEngine | None = None, db_path: str = "data/rag"
    ):
        if vector_store:
            self.store = vector_store
        else:
            eng = engine or EmbeddingEngine(provider="local")
            from pathlib import Path

            self.store = VectorStore(Path(db_path), eng)

    async def index_text(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None):
        await self.store.upsert(doc_id, text, metadata)

    async def index_chunks(self, chunks: list[dict[str, Any]], prefix: str = ""):
        items = []
        for i, chunk in enumerate(chunks):
            doc_id = f"{prefix}:{i}" if prefix else str(i)
            text: str = chunk.get("text", "")
            meta = {k: v for k, v in chunk.items() if k != "text"}
            items.append((doc_id, text, meta or None))
        if items:
            await self.store.upsert_batch(items)
            logger.info("Indexed {} chunks ({})", len(items), prefix or "root")

    async def index_document(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None):
        chunks = _semantic_chunk_text(text)
        return await self.index_chunks(chunks, prefix=doc_id)

    async def retrieve(self, query: str, k: int = 5, filter_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
