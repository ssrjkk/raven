from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.multi_modal_rag import Document, MultiModalRAG

_rag: MultiModalRAG | None = None
_RAG_PATH = Path(__file__).parent.parent / "data" / "rag_index.json"


def _get_rag() -> MultiModalRAG:
    global _rag
    if _rag is None:
        _rag = MultiModalRAG()
        _rag.set_index_path(str(_RAG_PATH))
        if _RAG_PATH.exists():
            try:
                _rag.load_index()
            except Exception as e:
                logger.warning("Failed to load RAG index: {}", e)
    return _rag


def _save_rag() -> None:
    try:
        _get_rag().save_index()
    except Exception as e:
        logger.error("Failed to save RAG index: {}", e)


def rag_index_text(document_id: str, text: str, source: str = "", metadata: str = "") -> str:
    rag = _get_rag()
    meta: dict[str, Any] = {}
    if metadata:
        try:
            import json

            meta = json.loads(metadata)
        except json.JSONDecodeError:
            meta = {"note": metadata}
    doc = Document(id=document_id, text=text, source=source, metadata=meta)
    chunk_ids = rag.index_document(doc)
    _save_rag()
    return f"Indexed {len(chunk_ids)} chunks from document '{document_id}'."


def rag_search(query: str, top_k: int = 5, include_images: bool = True) -> str:
    rag = _get_rag()
    try:
        results = rag.search(query, top_k=top_k, include_images=include_images)
    except Exception as e:
        logger.error("RAG search failed: {}", e)
        return f"[error] Search failed: {e}"
    if not results:
        return f"No results for '{query}'."
    lines = [f"Search results for '{query}':\n"]
    for r in results:
        modality_tag = f"[{r.modality.upper()}]" if r.modality != "text" else ""
        lines.append(f"  {modality_tag} score={r.score:.4f} | doc={r.document_id}")
        text_snippet = r.text[:150].replace("\n", " ")
        if text_snippet:
            lines.append(f"    {text_snippet}")
        if r.image_path:
            lines.append(f"    image: {r.image_path}")
        lines.append("")
    return "\n".join(lines)


def rag_stats() -> str:
    rag = _get_rag()
    stats = rag.get_stats()
    return (
        f"Multi-Modal RAG Statistics\n"
        f"- Documents: {stats['documents']}\n"
        f"- Chunks: {stats['chunks']}\n"
        f"- Total chars: {stats['total_chars']}\n"
        f"- Total images: {stats['total_images']}\n"
        f"- SentenceTransformer: {'available' if stats['sentence_transformer'] else 'not available'}\n"
        f"- CLIP: {'available' if stats['clip_available'] else 'not available'}\n"
        f"- ChromaDB: {'available' if stats['chroma_available'] else 'not available'}"
    )


def rag_remove_document(document_id: str) -> str:
    rag = _get_rag()
    if rag.remove_document(document_id):
        _save_rag()
        return f"Document '{document_id}' removed."
    return f"[error] Document '{document_id}' not found."


def register_rag_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="rag_index_text",
            description="Index text into the multi-modal RAG system",
            parameters={
                "document_id": {"type": "string", "description": "Unique document identifier", "required": True},
                "text": {"type": "string", "description": "Document text content", "required": True},
                "source": {"type": "string", "description": "Source label", "required": False},
                "metadata": {"type": "string", "description": "JSON metadata string", "required": False},
            },
            handler=rag_index_text,
            category="rag",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="rag_search",
            description="Search across text and image content using cross-modal retrieval",
            parameters={
                "query": {"type": "string", "description": "Search query", "required": True},
                "top_k": {"type": "integer", "description": "Number of results (default 5)", "required": False},
                "include_images": {
                    "type": "boolean",
                    "description": "Include image results (default true)",
                    "required": False,
                },
            },
            handler=rag_search,
            category="rag",
            timeout=15,
        )
    )
    registry.register(
        ToolSpec(
            name="rag_stats",
            description="Get statistics about the RAG index",
            parameters={},
            handler=rag_stats,
            category="rag",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="rag_remove_document",
            description="Remove a document and its chunks from the RAG index",
            parameters={
                "document_id": {"type": "string", "description": "Document identifier to remove", "required": True},
            },
            handler=rag_remove_document,
            category="rag",
            timeout=10,
        )
    )
