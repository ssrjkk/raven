from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Optional dependency detection — graceful fallback throughout
# ---------------------------------------------------------------------------

SentenceTransformer: Any = None
try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer

    SentenceTransformer = _SentenceTransformer
    _SENTENCE_TRANSFORMER_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMER_AVAILABLE = False

torch: Any = None
CLIPModel: Any = None
CLIPProcessor: Any = None
try:
    import torch as _torch
    from transformers import CLIPModel as _CLIPModel
    from transformers import CLIPProcessor as _CLIPProcessor

    torch = _torch
    CLIPModel = _CLIPModel
    CLIPProcessor = _CLIPProcessor
    _CLIP_AVAILABLE = True
except ImportError:
    _CLIP_AVAILABLE = False

chromadb: Any = None
Settings: Any = None
try:
    import chromadb as _chromadb
    from chromadb.config import Settings as _Settings

    chromadb = _chromadb
    Settings = _Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Citation:
    document_id: str
    source: str
    page: int
    chunk_index: int
    timestamp: float
    modality: str = "text"
    image_path: str = ""


@dataclass
class Document:
    id: str
    text: str = ""
    images: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    page: int = 0
    timestamp: float = 0.0


@dataclass
class Chunk:
    id: str
    text: str
    document_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)
    image_path: str = ""
    modality: str = "text"


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    image_path: str = ""
    modality: str = "text"
    citation: Citation | None = None


# ---------------------------------------------------------------------------
# Embedding utilities
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _text_to_embedding(text: str, dimension: int = 64) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    seed = int.from_bytes(h[:8], "big")
    rng = _SimpleRNG(seed)
    return [rng.random() for _ in range(dimension)]


class _SimpleRNG:
    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF

    def random(self) -> float:
        self._state = (self._state * 1103515245 + 12345) & 0xFFFFFFFF
        return self._state / 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Main RAG class
# ---------------------------------------------------------------------------


class MultiModalRAG:
    def __init__(
        self,
        dimension: int = 64,
        model_name: str = "all-MiniLM-L6-v2",
        clip_model_name: str = "openai/clip-vit-base-patch32",
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name
        self._clip_model_name = clip_model_name

        # In-memory state (kept for backward compat and fallback)
        self._documents: dict[str, Document] = {}
        self._chunks: list[Chunk] = []
        self._index_path: Path | None = None

        # Text embedder
        self._text_model: SentenceTransformer | None = None
        self._text_dim: int = dimension
        if _SENTENCE_TRANSFORMER_AVAILABLE:
            try:
                self._text_model = SentenceTransformer(model_name)
                self._text_dim = self._text_model.get_sentence_embedding_dimension()
                logger.info("Loaded SentenceTransformer model: {}", model_name)
            except Exception:
                logger.warning("Failed to load SentenceTransformer '{}', using hash fallback", model_name)

        # CLIP embedder for cross-modal search
        self._clip_processor: CLIPProcessor | None = None
        self._clip_model: CLIPModel | None = None
        self._clip_dim: int = 512
        if _CLIP_AVAILABLE:
            try:
                self._clip_processor = CLIPProcessor.from_pretrained(clip_model_name)
                self._clip_model = CLIPModel.from_pretrained(clip_model_name)
                self._clip_dim = getattr(self._clip_model.config, "projection_dim", 512)
                logger.info("Loaded CLIP model: {}", clip_model_name)
            except Exception:
                logger.warning("Failed to load CLIP model '{}'", clip_model_name)

        # Unique instance ID to isolate ChromaDB collections per instance
        self._instance_id = uuid.uuid4().hex[:8]

        # ChromaDB client (lazy-initialised)
        self._chroma_client: Any = None
        self._chroma_text_collection: Any = None
        self._chroma_clip_collection: Any = None

    # -- Path ----------------------------------------------------------------

    def set_index_path(self, path: str | Path) -> None:
        self._index_path = Path(path)

    def _chroma_db_path(self) -> Path | None:
        if not self._index_path:
            return None
        return self._index_path.with_suffix(".chroma")

    # -- Lazy ChromaDB initialisation ----------------------------------------

    def _ensure_chroma(self) -> None:
        if not _CHROMA_AVAILABLE:
            return
        if self._chroma_client is not None:
            return

        db_path = self._chroma_db_path()
        try:
            if db_path:
                db_path.mkdir(parents=True, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(
                    path=str(db_path),
                    settings=Settings(anonymized_telemetry=False),
                )
            else:
                self._chroma_client = chromadb.EphemeralClient()
        except Exception:
            logger.warning("Failed to initialise ChromaDB, falling back to in-memory")
            self._chroma_client = chromadb.EphemeralClient()

        try:
            self._chroma_text_collection = self._chroma_client.get_or_create_collection(
                name=f"text_chunks_{self._instance_id}",
                metadata={"hnsw:space": "cosine"},
            )
            self._chroma_clip_collection = self._chroma_client.get_or_create_collection(
                name=f"clip_chunks_{self._instance_id}",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            logger.warning("Failed to create ChromaDB collections, falling back to in-memory")
            self._chroma_client = None
            self._chroma_text_collection = None
            self._chroma_clip_collection = None

    # -- Embedding helpers ---------------------------------------------------

    def _embed_text(self, text: str) -> list[float]:
        if self._text_model is not None:
            emb = self._text_model.encode(text, normalize_embeddings=True)
            return list(emb)
        return _text_to_embedding(text, self._dimension)

    def _embed_text_clip(self, text: str) -> list[float]:
        if self._clip_model is None or self._clip_processor is None:
            return []
        inputs = self._clip_processor(text=[text], return_tensors="pt", padding=True)
        with torch.no_grad():
            emb = self._clip_model.get_text_features(**inputs)
        return list(emb[0])

    def _embed_image(self, image_path: str) -> list[float]:
        if self._clip_model is None or self._clip_processor is None:
            return []
        from PIL import Image as PILImage

        try:
            image = PILImage.open(image_path).convert("RGB")
        except Exception:
            logger.warning("Failed to open image: {}", image_path)
            return []
        inputs = self._clip_processor(images=image, return_tensors="pt")
        with torch.no_grad():
            emb = self._clip_model.get_image_features(**inputs)
        return list(emb[0])

    # -- Document indexing ---------------------------------------------------

    def index_document(self, document: Document, chunk_size: int = 500) -> list[str]:
        self._documents[document.id] = document
        chunk_ids: list[str] = []

        # --- Text chunks ---
        text = document.text
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i : i + chunk_size]
            chunk_index = i // chunk_size
            text_emb = self._embed_text(chunk_text)
            clip_emb = self._embed_text_clip(chunk_text) if _CLIP_AVAILABLE else []

            chunk = Chunk(
                id=uuid.uuid4().hex[:12],
                text=chunk_text,
                document_id=document.id,
                metadata={
                    **document.metadata,
                    "source": document.source,
                    "page": document.page,
                    "offset": i,
                    "chunk_index": chunk_index,
                },
                embedding=text_emb,
                modality="text",
            )
            self._chunks.append(chunk)
            chunk_ids.append(chunk.id)

            self._sync_to_chroma_text(chunk)
            if clip_emb:
                self._sync_to_chroma_clip(
                    chunk_id=chunk.id,
                    embedding=clip_emb,
                    document_id=document.id,
                    metadata=chunk.metadata,
                    text=chunk_text,
                    modality="text",
                )

        # --- Image chunks ---
        for img_idx, img_path in enumerate(document.images):
            img_emb = self._embed_image(img_path)
            chunk_index = -1 - img_idx

            chunk = Chunk(
                id=uuid.uuid4().hex[:12],
                text="",
                document_id=document.id,
                metadata={
                    **document.metadata,
                    "source": document.source,
                    "page": document.page,
                    "image_index": img_idx,
                    "chunk_index": chunk_index,
                },
                embedding=img_emb,
                image_path=img_path,
                modality="image",
            )
            self._chunks.append(chunk)
            chunk_ids.append(chunk.id)

            if img_emb:
                self._sync_to_chroma_clip(
                    chunk_id=chunk.id,
                    embedding=img_emb,
                    document_id=document.id,
                    metadata=chunk.metadata,
                    text=f"[IMAGE] {img_path}",
                    modality="image",
                )
            elif _CLIP_AVAILABLE:
                logger.warning("Empty CLIP embedding for image: {}", img_path)

        return chunk_ids

    def index_image(
        self,
        document_id: str,
        image_path: str,
        metadata: dict[str, Any] | None = None,
        source: str = "",
        page: int = 0,
    ) -> str:
        if document_id not in self._documents:
            doc = Document(
                id=document_id,
                source=source,
                page=page,
                timestamp=0.0,
                metadata=metadata or {},
            )
            self._documents[document_id] = doc

        img_emb = self._embed_image(image_path)
        chunk = Chunk(
            id=uuid.uuid4().hex[:12],
            text="",
            document_id=document_id,
            metadata={
                **(metadata or {}),
                "source": source,
                "page": page,
                "image_index": 0,
                "chunk_index": -1,
            },
            embedding=img_emb,
            image_path=image_path,
            modality="image",
        )
        self._chunks.append(chunk)

        if img_emb:
            self._sync_to_chroma_clip(
                chunk_id=chunk.id,
                embedding=img_emb,
                document_id=document_id,
                metadata=chunk.metadata,
                text=f"[IMAGE] {image_path}",
                modality="image",
            )

        return chunk.id

    # --- ChromaDB sync helpers ---

    def _sync_to_chroma_text(self, chunk: Chunk) -> None:
        self._ensure_chroma()
        if self._chroma_text_collection is None:
            return
        try:
            self._chroma_text_collection.add(
                ids=[chunk.id],
                embeddings=[chunk.embedding],
                metadatas=[{**chunk.metadata, "document_id": chunk.document_id}],
                documents=[chunk.text],
            )
        except Exception:
            logger.warning("ChromaDB text sync failed for chunk {}", chunk.id)

    def _sync_to_chroma_clip(
        self,
        chunk_id: str,
        embedding: list[float],
        document_id: str,
        metadata: dict[str, Any],
        text: str,
        modality: str,
    ) -> None:
        self._ensure_chroma()
        if self._chroma_clip_collection is None:
            return
        try:
            self._chroma_clip_collection.add(
                ids=[chunk_id],
                embeddings=[embedding],
                metadatas=[{**metadata, "document_id": document_id, "modality": modality}],
                documents=[text],
            )
        except Exception:
            logger.warning("ChromaDB CLIP sync failed for chunk {}", chunk_id)

    def _remove_from_chroma(self, chunk_ids: list[str]) -> None:
        self._ensure_chroma()
        if self._chroma_text_collection is not None:
            try:
                self._chroma_text_collection.delete(ids=chunk_ids)
            except Exception as exc:
                logger.debug("Chroma text delete failed for {} ids: {}", len(chunk_ids), exc)
        if self._chroma_clip_collection is not None:
            try:
                self._chroma_clip_collection.delete(ids=chunk_ids)
            except Exception as exc:
                logger.debug("Chroma CLIP delete failed for {} ids: {}", len(chunk_ids), exc)

    # -- Removal -------------------------------------------------------------

    def remove_document(self, document_id: str) -> bool:
        if document_id not in self._documents:
            return False
        del self._documents[document_id]
        removed = [c for c in self._chunks if c.document_id == document_id]
        self._chunks = [c for c in self._chunks if c.document_id != document_id]
        if removed:
            self._remove_from_chroma([c.id for c in removed])
        return True

    # -- Search --------------------------------------------------------------

    def _rank_chunks(self, query_embedding: list[float], chunks: list[Chunk]) -> list[tuple[float, Chunk]]:
        scored = [(_cosine_similarity(query_embedding, c.embedding), c) for c in chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _to_results(self, scored: list[tuple[float, Chunk]], top_k: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for score, chunk in scored[:top_k]:
            if score > 0:
                citation = Citation(
                    document_id=chunk.document_id,
                    source=chunk.metadata.get("source", ""),
                    page=chunk.metadata.get("page", 0),
                    chunk_index=chunk.metadata.get("chunk_index", 0),
                    timestamp=chunk.metadata.get("timestamp", 0.0),
                    modality=chunk.modality,
                    image_path=chunk.image_path,
                )
                results.append(
                    SearchResult(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        score=score,
                        metadata=dict(chunk.metadata),
                        image_path=chunk.image_path,
                        modality=chunk.modality,
                        citation=citation,
                    )
                )
        return results

    def _chroma_search(
        self,
        collection: Any,
        embedding: list[float],
        top_k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if collection is None or not embedding:
            return []
        try:
            where: dict[str, Any] | None = None
            if metadata_filter:
                where = {k: {"$eq": v} for k, v in metadata_filter.items()}
            raw = collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=where,
            )
        except Exception:
            logger.warning("ChromaDB query failed, falling back to in-memory")
            return []

        results: list[SearchResult] = []
        raw_ids: list[str] | None = raw.get("ids")
        if not raw_ids or not raw_ids[0]:
            return results

        raw_distances: list[list[float]] | None = raw.get("distances")
        raw_metadatas: list[list[dict[str, Any]]] | None = raw.get("metadatas")
        raw_documents: list[list[str]] | None = raw.get("documents")

        for i in range(len(raw_ids[0])):
            chunk_id = raw_ids[0][i] if i < len(raw_ids[0]) else ""
            distance = raw_distances[0][i] if raw_distances and i < len(raw_distances[0]) else 0.0
            meta: dict[str, Any] = raw_metadatas[0][i] if raw_metadatas and i < len(raw_metadatas[0]) else {}
            chunk_text = raw_documents[0][i] if raw_documents and i < len(raw_documents[0]) else ""
            modality = meta.get("modality", "text")
            image_path = meta.get("image_path", "")

            citation = Citation(
                document_id=meta.get("document_id", ""),
                source=meta.get("source", ""),
                page=meta.get("page", 0),
                chunk_index=meta.get("chunk_index", 0),
                timestamp=meta.get("timestamp", 0.0),
                modality=modality,
                image_path=image_path,
            )
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    document_id=meta.get("document_id", ""),
                    text=chunk_text,
                    score=1.0 - distance,
                    metadata=meta,
                    image_path=image_path,
                    modality=modality,
                    citation=citation,
                )
            )
        return results

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_images: bool = True,
    ) -> list[SearchResult]:
        query_embedding = self._embed_text(query)

        text_results: list[SearchResult] = []
        image_results: list[SearchResult] = []

        # ChromaDB path
        self._ensure_chroma()
        if self._chroma_text_collection is not None:
            text_results = self._chroma_search(self._chroma_text_collection, query_embedding, top_k)
        else:
            scored = self._rank_chunks(
                query_embedding,
                [c for c in self._chunks if c.modality == "text"],
            )
            text_results = self._to_results(scored, top_k)

        # Cross-modal: CLIP text query → CLIP image & text embeddings
        if include_images and self._clip_model is not None:
            clip_query_emb = self._embed_text_clip(query)
            if clip_query_emb and self._chroma_clip_collection is not None:
                image_results = self._chroma_search(self._chroma_clip_collection, clip_query_emb, top_k)
            elif clip_query_emb:
                clip_chunks = [c for c in self._chunks if c.modality == "image" and c.embedding]
                if clip_chunks:
                    scored = self._rank_chunks(clip_query_emb, clip_chunks)
                    image_results = self._to_results(scored, top_k)

        # Merge: interleave results sorted by score, dedup by chunk_id
        seen: set[str] = set()
        merged: list[SearchResult] = []

        all_sorted = sorted(text_results + image_results, key=lambda r: r.score, reverse=True)
        for r in all_sorted:
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                merged.append(r)
                if len(merged) >= top_k:
                    break

        return merged

    def search_by_metadata(
        self,
        query: str,
        metadata_filter: dict[str, Any],
        top_k: int = 5,
    ) -> list[SearchResult]:
        query_embedding = self._embed_text(query)

        self._ensure_chroma()
        if self._chroma_text_collection is not None:
            results = self._chroma_search(self._chroma_text_collection, query_embedding, top_k, metadata_filter)
            if results:
                return results

        filtered = [c for c in self._chunks if all(c.metadata.get(k) == v for k, v in metadata_filter.items())]
        scored = self._rank_chunks(query_embedding, filtered)
        return self._to_results(scored, top_k)

    # -- Citations -----------------------------------------------------------

    def get_citations(self, chunk_ids: list[str]) -> list[Citation]:
        citations: list[Citation] = []
        for chunk in self._chunks:
            if chunk.id in chunk_ids:
                citations.append(
                    Citation(
                        document_id=chunk.document_id,
                        source=chunk.metadata.get("source", ""),
                        page=chunk.metadata.get("page", 0),
                        chunk_index=chunk.metadata.get("chunk_index", 0),
                        timestamp=chunk.metadata.get("timestamp", 0.0),
                        modality=chunk.modality,
                        image_path=chunk.image_path,
                    )
                )
        return citations

    # -- Persistence ---------------------------------------------------------

    def save_index(self, path: str | Path | None = None) -> None:
        save_path = Path(path) if path else self._index_path
        if not save_path:
            return

        data = {
            "documents": {
                did: {
                    "id": d.id,
                    "text": d.text,
                    "images": d.images,
                    "metadata": d.metadata,
                    "source": d.source,
                    "page": d.page,
                    "timestamp": d.timestamp,
                }
                for did, d in self._documents.items()
            },
            "chunks": [
                {
                    "id": c.id,
                    "text": c.text,
                    "document_id": c.document_id,
                    "metadata": c.metadata,
                    "embedding": c.embedding,
                    "image_path": c.image_path,
                    "modality": c.modality,
                }
                for c in self._chunks
            ],
        }
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load_index(self, path: str | Path | None = None) -> None:
        load_path = Path(path) if path else self._index_path
        if not load_path or not load_path.exists():
            return
        data = json.loads(load_path.read_text(encoding="utf-8"))

        self._documents = {did: Document(**d) for did, d in data.get("documents", {}).items()}
        self._chunks = []
        for c in data.get("chunks", []):
            chunk = Chunk(
                id=c["id"],
                text=c["text"],
                document_id=c["document_id"],
                metadata=c.get("metadata", {}),
                embedding=c.get("embedding", []),
                image_path=c.get("image_path", ""),
                modality=c.get("modality", "text"),
            )
            self._chunks.append(chunk)

            self._sync_to_chroma_text(chunk)
            if c.get("modality") == "image" and chunk.embedding:
                self._sync_to_chroma_clip(
                    chunk_id=chunk.id,
                    embedding=chunk.embedding,
                    document_id=chunk.document_id,
                    metadata=chunk.metadata,
                    text=chunk.text or f"[IMAGE] {chunk.image_path}",
                    modality=chunk.modality,
                )

    async def async_save_index(self, path: str | Path | None = None) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.save_index, path)

    async def async_load_index(self, path: str | Path | None = None) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.load_index, path)

    # -- Stats ---------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        return {
            "documents": len(self._documents),
            "chunks": len(self._chunks),
            "dimension": self._dimension,
            "text_dim": self._text_dim,
            "clip_dim": self._clip_dim,
            "total_chars": sum(len(d.text) for d in self._documents.values()),
            "total_images": sum(len(d.images) for d in self._documents.values()),
            "sentence_transformer": self._text_model is not None,
            "clip_available": _CLIP_AVAILABLE and self._clip_model is not None,
            "chroma_available": _CHROMA_AVAILABLE and self._chroma_client is not None,
        }
