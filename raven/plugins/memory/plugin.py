from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from raven.plugins.code.plugin import run_python as code_run_python

PLUGIN_NAME = "memory"
PLUGIN_DESCRIPTION = "Store and retrieve information from long-term memory"

_client = None
_collection = None
_lock = asyncio.Lock()


async def _ensure_db():
    global _client, _collection
    async with _lock:
        if _collection is not None:
            return _collection
        try:
            import chromadb

            _client = await asyncio.to_thread(chromadb.Client)
            _collection = await asyncio.to_thread(_client.get_or_create_collection, "raven_memory")
            return _collection
        except Exception as e:
            logger.warning("ChromaDB not available, using fallback: {}", e)
            return None


_fallback: dict[str, list[dict[str, Any]]] = {}


async def remember(key: str, value: str) -> str:
    collection = await _ensure_db()
    if collection:
        try:
            await asyncio.to_thread(collection.upsert, documents=[value], ids=[key])
            return f"Remembered '{key}'"
        except Exception as e:
            logger.warning("[memory] ChromaDB upsert failed: {}", e)
    _fallback[key] = [{"document": value}]
    return f"Remembered '{key}' (fallback)"


async def recall(key: str) -> str:
    collection = await _ensure_db()
    if collection:
        try:
            result = await asyncio.to_thread(collection.get, ids=[key])
            docs = result.get("documents", [])
            if docs and isinstance(docs[0], str):
                return docs[0][:2000]
        except Exception as e:
            logger.warning("[memory] ChromaDB recall failed: {}", e)
    if key in _fallback:
        items = _fallback[key]
        if items:
            val: str = items[0].get("document", "")
            return val[:2000]
    return f"Nothing found for '{key}'"


async def forget(key: str) -> str:
    collection = await _ensure_db()
    if collection:
        try:
            await asyncio.to_thread(collection.delete, ids=[key])
        except Exception as e:
            logger.warning("[memory] ChromaDB delete failed: {}", e)
    _fallback.pop(key, None)
    return f"Forgot '{key}'"


async def search_memory(query: str, n_results: int = 5) -> str:
    collection = await _ensure_db()
    if collection:
        try:
            results = await asyncio.to_thread(collection.query, query_texts=[query], n_results=n_results)
            docs = results.get("documents", [[]])[0]
            ids = results.get("ids", [[]])[0]
            if docs:
                lines = [f"- `{doc_id}`: {doc[:200]}" for doc_id, doc in zip(ids, docs, strict=False)]
                return "Memory search results:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("[memory] ChromaDB search failed: {}", e)
    return "Search not available (fallback mode). Use recall with exact key."


async def list_keys() -> str:
    collection = await _ensure_db()
    if collection:
        try:
            all_data = await asyncio.to_thread(collection.get)
            ids = all_data.get("ids", [])
            if ids:
                return "Memory keys:\n" + "\n".join(f"- `{k}`" for k in ids)
        except Exception as e:
            logger.warning("[memory] ChromaDB list_keys failed: {}", e)
    if _fallback:
        return "Memory keys (fallback):\n" + "\n".join(f"- `{k}`" for k in _fallback)
    return "No memories stored."


async def store_knowledge(topic: str, content: str) -> str:
    doc = f"# {topic}\n{content}"
    await remember(f"knowledge:{topic}", doc)
    return f"Stored knowledge about '{topic}'"


async def retrieve_knowledge(topic: str) -> str:
    return await recall(f"knowledge:{topic}")


async def run_code_and_remember(code: str, key: str) -> str:
    result = await code_run_python(code)
    await remember(key, result)
    return f"Stored result under '{key}':\n{result[:500]}"
