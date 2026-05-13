from __future__ import annotations

import asyncio

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
            _client = chromadb.Client()
            _collection = _client.get_or_create_collection("raven_memory")
            return _collection
        except Exception as e:
            logger.warning("ChromaDB not available, using fallback: {}", e)
            return None


# In-memory fallback
_fallback: dict[str, list[dict]] = {}


async def remember(key: str, value: str) -> str:
    """Store a value in memory. Args: key (str): Memory key, value (str): Value to store"""
    collection = await _ensure_db()
    if collection:
        try:
            collection.upsert(documents=[value], ids=[key])
            return f"Remembered '{key}'"
        except Exception:
            pass
    _fallback[key] = [{"document": value}]
    return f"Remembered '{key}' (fallback)"


async def recall(key: str) -> str:
    """Retrieve a value from memory. Args: key (str): Memory key"""
    collection = await _ensure_db()
    if collection:
        try:
            result = collection.get(ids=[key])
            docs = result.get("documents", [])
            if docs and docs[0]:
                return docs[0][:2000]
        except Exception:
            pass
    if key in _fallback:
        items = _fallback[key]
        if items:
            return items[0].get("document", "")[:2000]
    return f"Nothing found for '{key}'"


async def forget(key: str) -> str:
    """Delete a memory. Args: key (str): Memory key to forget"""
    collection = await _ensure_db()
    if collection:
        try:
            collection.delete(ids=[key])
        except Exception:
            pass
    _fallback.pop(key, None)
    return f"Forgot '{key}'"


async def search_memory(query: str, n_results: int = 5) -> str:
    """Search memory by semantic similarity. Args: query (str): Search query, n_results (int): Max results"""
    collection = await _ensure_db()
    if collection:
        try:
            results = collection.query(query_texts=[query], n_results=n_results)
            docs = results.get("documents", [[]])[0]
            ids = results.get("ids", [[]])[0]
            if docs:
                lines = [f"- `{ids[i]}`: {docs[i][:200]}" for i in range(len(docs))]
                return "Memory search results:\n" + "\n".join(lines)
        except Exception:
            pass
    return "Search not available (fallback mode). Use recall with exact key."


async def list_keys() -> str:
    """List all memory keys"""
    collection = await _ensure_db()
    if collection:
        try:
            all_data = collection.get()
            ids = all_data.get("ids", [])
            if ids:
                return "Memory keys:\n" + "\n".join(f"- `{k}`" for k in ids)
        except Exception:
            pass
    if _fallback:
        return "Memory keys (fallback):\n" + "\n".join(f"- `{k}`" for k in _fallback)
    return "No memories stored."


async def store_knowledge(topic: str, content: str) -> str:
    """Store structured knowledge about a topic. Args: topic (str): Topic name, content (str): Knowledge content"""
    doc = f"# {topic}\n{content}"
    await remember(f"knowledge:{topic}", doc)
    return f"Stored knowledge about '{topic}'"


async def retrieve_knowledge(topic: str) -> str:
    """Retrieve stored knowledge about a topic. Args: topic (str): Topic name"""
    return await recall(f"knowledge:{topic}")


async def run_code_and_remember(code: str, key: str) -> str:
    """Run Python code and remember its result. Args: code (str): Python code, key (str): Key to store under"""
    result = await code_run_python(code)
    await remember(key, result)
    return f"Stored result under '{key}':\n{result[:500]}"
