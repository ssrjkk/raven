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
    """Store a text under a key so later turns can recall it.

    key: Identifier to recall or forget this value by; storing the same key again replaces the old value.
    value: The text to keep. Only the first 2000 characters come back from recall.
    """
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
    """Return the text stored under one exact key, or say that nothing is stored there.

    key: The identifier passed to remember or store_knowledge. Recall does not search, so a partly correct key
        returns 'Nothing found'.
    """
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
    """Delete the text stored under one key from both the vector store and the in-process fallback.

    key: The identifier to drop. A key holding nothing is reported as such, so the answer says whether anything was
        actually removed.
    """
    collection = await _ensure_db()
    removed = False
    if collection:
        try:
            existing = await asyncio.to_thread(collection.get, ids=[key])
            if existing.get("ids", []):
                await asyncio.to_thread(collection.delete, ids=[key])
                removed = True
        except Exception as e:
            logger.warning("[memory] ChromaDB delete failed: {}", e)
    if key in _fallback:
        _fallback.pop(key, None)
        removed = True
    return f"Forgot '{key}'" if removed else f"Nothing stored under '{key}'"


async def search_memory(query: str, n_results: int = 5) -> str:
    """Search stored memories by meaning and return the closest ones with their keys.

    query: What to look for; the match is on the sense of the text, not an exact key.
    n_results: How many hits to return, clamped to 1..50. Each hit is cut to 200 characters, so use recall for the
        full text.
    """
    collection = await _ensure_db()
    n = max(1, min(int(n_results), 50))
    if collection:
        try:
            results = await asyncio.to_thread(collection.query, query_texts=[query], n_results=n)
            docs = results.get("documents", [[]])[0]
            ids = results.get("ids", [[]])[0]
            if docs:
                lines = [f"- `{doc_id}`: {doc[:200]}" for doc_id, doc in zip(ids, docs, strict=False)]
                return "Memory search results:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("[memory] ChromaDB search failed: {}", e)
    return "Search not available (fallback mode). Use recall with exact key."


async def list_keys() -> str:
    """List every key currently in memory, one per line.

    The keys are shown in whatever order the store returns; an empty memory reports 'No memories stored.'.
    """
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
    """Store a markdown document about one topic under the key 'knowledge:<topic>'.

    topic: What the document is about; it becomes part of the key, so reuse the same wording to find it again.
    content: Document body, written below a '# <topic>' heading.
    """
    doc = f"# {topic}\n{content}"
    await remember(f"knowledge:{topic}", doc)
    return f"Stored knowledge about '{topic}'"


async def retrieve_knowledge(topic: str) -> str:
    """Return the document stored by store_knowledge for one exact topic.

    topic: The topic passed to store_knowledge; the lookup is on the key 'knowledge:<topic>', not a search.
    """
    return await recall(f"knowledge:{topic}")


async def run_code_and_remember(code: str, key: str) -> str:
    """Run Python code and store whatever it printed and returned under a memory key.

    code: Source for the code plugin's sandboxed runner; the last expression's value is part of the result. Refused
        by the code sandbox stays refused here.
    key: Memory key the result is stored under, so recall can read it in a later turn.
    """
    result = await code_run_python(code)
    await remember(key, result)
    return f"Stored result under '{key}':\n{result[:500]}"
