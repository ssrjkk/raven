from __future__ import annotations
import os
import json
import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger
from raven.core.config import settings

PLUGIN_NAME = "memory"
PLUGIN_DESCRIPTION = "Vector memory — remember and recall facts from conversations"

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    db_path = str(settings.resolved_vector_db_path)
    os.makedirs(db_path, exist_ok=True)
    _client = chromadb.PersistentClient(path=db_path, settings=ChromaSettings(anonymized_telemetry=False))
    _collection = _client.get_or_create_collection(name="raven_memory", metadata={"hnsw:space": "cosine"})
    return _collection


async def remember(content: str, metadata: str = "{}") -> str:
    """Save content to long-term memory. Args: content (str): Text to remember, metadata (str): Optional JSON metadata"""
    try:
        collection = _get_collection()
        doc_id = str(hash(content))
        meta = json.loads(metadata) if isinstance(metadata, str) else {}
        collection.add(documents=[content], ids=[doc_id], metadatas=[meta])
        return f"Remembered: {content[:100]}..."
    except Exception as e:
        logger.error("Memory remember failed: {}", e)
        return f"Failed to remember: {e}"


async def recall(query: str, limit: int = 5) -> str:
    """Find relevant memories by semantic similarity. Args: query (str): Search query, limit (int): Max results"""
    try:
        collection = _get_collection()
        results = collection.query(query_texts=[query], n_results=min(limit, 20))
        if not results["documents"] or not results["documents"][0]:
            return "No relevant memories found."
        memories = []
        for i, doc in enumerate(results["documents"][0]):
            dist = results["distances"][0][i] if results.get("distances") else 0
            memories.append(f"- {doc} (relevance: {1 - dist:.2f})")
        return "Relevant memories:\n" + "\n".join(memories)
    except Exception as e:
        logger.error("Memory recall failed: {}", e)
        return f"Failed to recall: {e}"


async def forget(query: str) -> str:
    """Remove memories matching a query. Args: query (str): Query to find memories to delete"""
    try:
        collection = _get_collection()
        results = collection.query(query_texts=[query], n_results=10)
        if results["ids"] and results["ids"][0]:
            collection.delete(ids=results["ids"][0])
            return f"Forgot {len(results['ids'][0])} memories."
        return "No matching memories found."
    except Exception as e:
        logger.error("Memory forget failed: {}", e)
        return f"Failed to forget: {e}"
