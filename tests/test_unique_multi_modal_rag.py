from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import pytest

from raven.unique import multi_modal_rag as mmr
from raven.unique.multi_modal_rag import (
    Chunk,
    Citation,
    Document,
    MultiModalRAG,
    SearchResult,
    _cosine_similarity,
    _SimpleRNG,
    _text_to_embedding,
)


class _FakeTextModel:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def get_sentence_embedding_dimension(self) -> int:
        return 8

    def encode(self, text: str, normalize_embeddings: bool = True) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


class _FakeNoGrad:
    def __enter__(self) -> _FakeNoGrad:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        return False


class _FakeTorch:
    def no_grad(self) -> _FakeNoGrad:
        return _FakeNoGrad()


class _FakeClipProcessor:
    def __init__(self) -> None:
        self.recorded: dict[str, object] = {}

    def __call__(self, *args: object, **kwargs: object) -> dict[str, bool]:
        self.recorded = dict(kwargs)
        return {"dummy": True}

    @classmethod
    def from_pretrained(cls, name: str) -> _FakeClipProcessor:
        return cls()


class _FakeClipConfig:
    projection_dim = 16


class _FakeClipModel:
    config = _FakeClipConfig()

    def get_text_features(self, **inputs: object) -> list[list[float]]:
        return [[0.1] * 16]

    def get_image_features(self, **inputs: object) -> list[list[float]]:
        return [[0.2] * 16]

    @classmethod
    def from_pretrained(cls, name: str) -> _FakeClipModel:
        return cls()


def _make_rag_with_st(monkeypatch: pytest.MonkeyPatch) -> MultiModalRAG:
    monkeypatch.setattr(mmr, "_SENTENCE_TRANSFORMER_AVAILABLE", True)
    monkeypatch.setattr(mmr, "SentenceTransformer", _FakeTextModel)
    return MultiModalRAG(dimension=32)


def _make_rag_with_clip(monkeypatch: pytest.MonkeyPatch) -> MultiModalRAG:
    monkeypatch.setattr(mmr, "_CLIP_AVAILABLE", True)
    monkeypatch.setattr(mmr, "CLIPProcessor", _FakeClipProcessor)
    monkeypatch.setattr(mmr, "CLIPModel", _FakeClipModel)
    monkeypatch.setattr(mmr, "torch", _FakeTorch())
    return MultiModalRAG(dimension=32)



@pytest.fixture(autouse=True)
def _optional_embedders_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit suite must not pull `openai/clip-vit-base-patch32` over the network just because
    transformers happens to be installed; the CLIP and SentenceTransformer paths have their own
    tests that install fakes and re-enable the flag explicitly."""
    monkeypatch.setattr(mmr, "_CLIP_AVAILABLE", False)
    monkeypatch.setattr(mmr, "_SENTENCE_TRANSFORMER_AVAILABLE", False)


class TestMultiModalRAG:
    def setup_method(self) -> None:
        self.rag = MultiModalRAG(dimension=32)

    def test_index_document(self):
        doc = Document(id="d1", text="Hello world, this is a test document.")
        chunk_ids = self.rag.index_document(doc)
        assert len(chunk_ids) >= 1

    def test_remove_document(self):
        doc = Document(id="d1", text="Hello world")
        self.rag.index_document(doc)
        assert self.rag.remove_document("d1") is True
        assert self.rag.remove_document("d1") is False

    def test_search(self):
        self.rag.index_document(Document(id="d1", text="Python is a programming language"))
        self.rag.index_document(Document(id="d2", text="Cats are great pets"))
        results = self.rag.search("programming", top_k=2)
        assert len(results) >= 1
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_by_metadata(self):
        doc = Document(id="d1", text="Machine learning is fun",
                       metadata={"topic": "ai"})
        self.rag.index_document(doc)
        results = self.rag.search_by_metadata("learning", {"topic": "ai"}, top_k=5)
        assert len(results) >= 1

    def test_search_by_metadata_no_match(self):
        doc = Document(id="d1", text="Machine learning is fun",
                       metadata={"topic": "ai"})
        self.rag.index_document(doc)
        results = self.rag.search_by_metadata("learning", {"topic": "database"})
        assert len(results) == 0

    def test_save_and_load_index(self, tmp_path):
        self.rag.index_document(Document(id="d1", text="Test content"))
        path = tmp_path / "index.json"
        self.rag.save_index(path)
        assert path.exists()

        rag2 = MultiModalRAG(dimension=32)
        rag2.load_index(path)
        assert rag2.get_stats()["documents"] == 1

    def test_get_stats(self):
        self.rag.index_document(Document(id="d1", text="Hello"))
        stats = self.rag.get_stats()
        assert stats["documents"] == 1
        assert stats["chunks"] >= 1

    def test_search_empty(self):
        results = self.rag.search("anything")
        assert results == []

    def test_large_document_chunking(self):
        text = "word " * 2000
        doc = Document(id="d1", text=text)
        chunk_ids = self.rag.index_document(doc, chunk_size=500)
        assert len(chunk_ids) >= 3


class _FakeCollection:
    def __init__(self, response: dict[str, Any] | None = None, raises: bool = False) -> None:
        self._resp = response if response is not None else {
            "ids": [["c1"]],
            "distances": [[0.1]],
            "metadatas": [[{"document_id": "d1", "source": "s", "page": 0, "chunk_index": 0, "modality": "text"}]],
            "documents": [["hit text"]],
        }
        self._raises = raises
        self.added: list[dict[str, Any]] = []
        self.deleted: list[list[str]] = []

    def query(self, **kwargs: object) -> dict[str, Any]:
        if self._raises:
            msg = "query failed"
            raise RuntimeError(msg)
        return self._resp

    def add(self, **kwargs: object) -> None:
        self.added.append(dict(kwargs))

    def delete(self, **kwargs: object) -> None:
        self.deleted.append(list(cast("list[str]", kwargs.get("ids", []))))


class _FakeChromaClient:
    def __init__(self, fail_create: bool = False) -> None:
        self._fail_create = fail_create

    def get_or_create_collection(self, name: str = "", metadata: dict[str, Any] | None = None) -> _FakeCollection:
        if self._fail_create:
            msg = "cannot create"
            raise RuntimeError(msg)
        return _FakeCollection()


class _FakeChromaModule:
    def __init__(self, fail_persistent: bool = False, fail_create: bool = False) -> None:
        self.fail_persistent = fail_persistent
        self.fail_create = fail_create

    def PersistentClient(self, path: str = "", settings: Any = None) -> _FakeChromaClient:
        if self.fail_persistent:
            msg = "no persistent"
            raise RuntimeError(msg)
        return _FakeChromaClient(fail_create=self.fail_create)

    def EphemeralClient(self) -> _FakeChromaClient:
        return _FakeChromaClient(fail_create=self.fail_create)


def _enable_fake_chroma(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_persistent: bool = False,
    fail_create: bool = False,
) -> None:
    monkeypatch.setattr(mmr, "_CHROMA_AVAILABLE", True)
    monkeypatch.setattr(mmr, "chromadb", _FakeChromaModule(fail_persistent=fail_persistent, fail_create=fail_create))
    monkeypatch.setattr(mmr, "Settings", lambda **kwargs: None)


def _make_png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (4, 4), "red").save(path)


class TestEmbeddingUtils:
    def test_cosine_similarity_normal(self):
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_similarity_zero_norm(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_text_to_embedding_deterministic(self):
        a = _text_to_embedding("hello", 16)
        b = _text_to_embedding("hello", 16)
        assert a == b
        assert len(a) == 16

    def test_simple_rng_range(self):
        rng = _SimpleRNG(12345)
        values = [rng.random() for _ in range(10)]
        assert all(0.0 <= v <= 1.0 for v in values)


class TestIndexPathAndChroma:
    def test_set_index_path_and_db_path(self, tmp_path: Path):
        rag = MultiModalRAG(dimension=32)
        assert rag._chroma_db_path() is None
        rag.set_index_path(tmp_path / "idx.json")
        assert rag._chroma_db_path() == tmp_path / "idx.chroma"

    def test_persistent_client_creates_collections(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch)
        rag = MultiModalRAG(dimension=32)
        rag.set_index_path(tmp_path / "idx.json")
        rag._ensure_chroma()
        assert rag._chroma_client is not None
        assert rag._chroma_text_collection is not None
        assert rag._chroma_clip_collection is not None
        assert rag.get_stats()["chroma_available"] is True

    def test_ephemeral_client_when_no_index_path(self, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch)
        rag = MultiModalRAG(dimension=32)
        rag._ensure_chroma()
        assert rag._chroma_client is not None
        assert rag._chroma_text_collection is not None

    def test_persistent_failure_falls_back_to_ephemeral(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch, fail_persistent=True)
        rag = MultiModalRAG(dimension=32)
        rag.set_index_path(tmp_path / "idx.json")
        rag._ensure_chroma()
        assert rag._chroma_client is not None
        assert rag._chroma_text_collection is not None

    def test_collection_creation_failure_disables_chroma(self, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch, fail_create=True)
        rag = MultiModalRAG(dimension=32)
        rag._ensure_chroma()
        assert rag._chroma_client is None
        assert rag._chroma_text_collection is None

    def test_ensure_chroma_noop_when_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mmr, "_CHROMA_AVAILABLE", False)
        rag = MultiModalRAG(dimension=32)
        rag._ensure_chroma()
        assert rag._chroma_client is None

    def test_chroma_search_parses_results(self):
        rag = MultiModalRAG(dimension=32)
        resp = {
            "ids": [["c1", "c2"]],
            "distances": [[0.1, 0.2]],
            "metadatas": [
                [
                    {"document_id": "d1", "source": "s", "page": 1, "chunk_index": 0, "modality": "image", "image_path": "p.png"},
                    {"document_id": "d2"},
                ]
            ],
            "documents": [["text one", "text two"]],
        }
        results = rag._chroma_search(_FakeCollection(resp), [0.1, 0.2], 5, {"document_id": "d1"})
        assert len(results) == 2
        assert results[0].modality == "image"
        assert results[0].citation is not None

    def test_chroma_search_no_collection_or_embedding(self):
        rag = MultiModalRAG(dimension=32)
        assert rag._chroma_search(None, [0.1], 3) == []
        assert rag._chroma_search(_FakeCollection({"ids": [[]]}), [], 3) == []

    def test_chroma_search_empty_ids(self):
        rag = MultiModalRAG(dimension=32)
        assert rag._chroma_search(_FakeCollection({"ids": [[]]}), [0.1, 0.2], 3) == []

    def test_chroma_search_query_error(self):
        rag = MultiModalRAG(dimension=32)
        assert rag._chroma_search(_FakeCollection({}, raises=True), [0.1, 0.2], 3) == []

    def test_search_text_via_chroma(self, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch)
        rag = MultiModalRAG(dimension=32)
        rag._ensure_chroma()
        results = rag.search("query", top_k=3)
        assert len(results) >= 1
        assert results[0].chunk_id == "c1"

    def test_search_by_metadata_via_chroma(self, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch)
        rag = MultiModalRAG(dimension=32)
        rag._ensure_chroma()
        results = rag.search_by_metadata("query", {"document_id": "d1"}, top_k=3)
        assert len(results) >= 1

    def test_search_images_via_chroma_clip(self, monkeypatch: pytest.MonkeyPatch):
        _enable_fake_chroma(monkeypatch)
        rag = _make_rag_with_clip(monkeypatch)
        rag._ensure_chroma()
        results = rag.search("query", top_k=3, include_images=True)
        assert isinstance(results, list)


class TestSentenceTransformerInit:
    def test_init_with_text_model(self, monkeypatch: pytest.MonkeyPatch):
        rag = _make_rag_with_st(monkeypatch)
        assert rag._text_model is not None
        assert rag._text_dim == 8
        emb = rag._embed_text("hello")
        assert emb == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        assert rag.get_stats()["sentence_transformer"] is True

    def test_init_text_model_load_failure(self, monkeypatch: pytest.MonkeyPatch):
        class _FailingModel:
            def __init__(self, name: str) -> None:
                msg = "load failed"
                raise RuntimeError(msg)

        monkeypatch.setattr(mmr, "_SENTENCE_TRANSFORMER_AVAILABLE", True)
        monkeypatch.setattr(mmr, "SentenceTransformer", _FailingModel)
        rag = MultiModalRAG(dimension=32)
        assert rag._text_model is None
        assert len(rag._embed_text("x")) == 32


class TestClipInitAndEmbeddings:
    def test_init_with_clip(self, monkeypatch: pytest.MonkeyPatch):
        rag = _make_rag_with_clip(monkeypatch)
        assert rag._clip_model is not None
        assert rag._clip_dim == 16
        assert rag.get_stats()["clip_available"] is True

    def test_init_clip_load_failure(self, monkeypatch: pytest.MonkeyPatch):
        class _Failing:
            @classmethod
            def from_pretrained(cls, name: str) -> None:
                msg = "clip load failed"
                raise RuntimeError(msg)

        monkeypatch.setattr(mmr, "_CLIP_AVAILABLE", True)
        monkeypatch.setattr(mmr, "CLIPProcessor", _FakeClipProcessor)
        monkeypatch.setattr(mmr, "CLIPModel", _Failing)
        rag = MultiModalRAG(dimension=32)
        assert rag._clip_model is None

    def test_embed_text_clip(self, monkeypatch: pytest.MonkeyPatch):
        rag = _make_rag_with_clip(monkeypatch)
        assert rag._embed_text_clip("hello") == [0.1] * 16

    def test_embed_text_clip_no_model(self):
        rag = MultiModalRAG(dimension=32)
        assert rag._embed_text_clip("hello") == []

    def test_long_text_is_truncated_to_the_clip_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # CLIP's text encoder has a hard positional limit; without truncation a 500-char chunk
        # raised ValueError inside forward() and index_document died
        rag = _make_rag_with_clip(monkeypatch)
        rag._embed_text_clip("word " * 2000)
        processor = rag._clip_processor
        assert processor is not None
        assert processor.recorded.get("truncation") is True
        assert processor.recorded.get("max_length") == 77

    def test_embed_image_valid(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        rag = _make_rag_with_clip(monkeypatch)
        png = tmp_path / "img.png"
        _make_png(png)
        assert rag._embed_image(str(png)) == [0.2] * 16

    def test_embed_image_invalid(self, monkeypatch: pytest.MonkeyPatch):
        rag = _make_rag_with_clip(monkeypatch)
        assert rag._embed_image("does_not_exist.png") == []

    def test_embed_image_no_model(self):
        rag = MultiModalRAG(dimension=32)
        assert rag._embed_image("anything.png") == []


class TestImageIndexing:
    def test_index_document_with_images(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        rag = _make_rag_with_clip(monkeypatch)
        png = tmp_path / "img.png"
        _make_png(png)
        doc = Document(id="d1", text="some text", images=[str(png), str(tmp_path / "missing.png")])
        chunk_ids = rag.index_document(doc)
        assert len(chunk_ids) >= 2
        image_chunks = [c for c in rag._chunks if c.modality == "image"]
        assert len(image_chunks) == 2

    def test_index_image_new_document(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        rag = _make_rag_with_clip(monkeypatch)
        png = tmp_path / "img.png"
        _make_png(png)
        cid = rag.index_image("d1", str(png), metadata={"k": "v"}, source="s", page=2)
        assert cid
        assert "d1" in rag._documents
        # second call reuses existing document
        cid2 = rag.index_image("d1", str(png))
        assert cid2

    def test_index_image_without_clip(self, tmp_path: Path):
        rag = MultiModalRAG(dimension=32)
        cid = rag.index_image("d1", str(tmp_path / "nope.png"))
        assert cid


class TestSyncHelpers:
    def test_sync_text_add_failure(self, monkeypatch: pytest.MonkeyPatch):
        rag = MultiModalRAG(dimension=32)
        rag._chroma_text_collection = _FakeCollection({}, raises=True)
        # add raising should be swallowed by the sync helper
        boom = _FakeCollection({})

        def _raise(**kwargs: object) -> None:
            msg = "add failed"
            raise RuntimeError(msg)

        boom.add = _raise  # type: ignore[method-assign]
        rag._chroma_text_collection = boom
        chunk = Chunk(id="c1", text="t", document_id="d1", embedding=[0.1, 0.2])
        rag._sync_to_chroma_text(chunk)
        assert boom.added == []

    def test_sync_clip_add_failure(self):
        rag = MultiModalRAG(dimension=32)

        def _raise(**kwargs: object) -> None:
            msg = "clip add failed"
            raise RuntimeError(msg)

        coll = _FakeCollection({})
        coll.add = _raise  # type: ignore[method-assign]
        rag._chroma_clip_collection = coll
        rag._sync_to_chroma_clip("c1", [0.1], "d1", {}, "t", "text")
        assert coll.added == []

    def test_sync_text_no_collection(self):
        rag = MultiModalRAG(dimension=32)
        monkeypatch_off: Any = rag
        monkeypatch_off._chroma_text_collection = None
        monkeypatch_off._ensure_chroma = lambda: None
        chunk = Chunk(id="c1", text="t", document_id="d1", embedding=[0.1])
        rag._sync_to_chroma_text(chunk)

    def test_remove_from_chroma_delete_errors(self, monkeypatch: pytest.MonkeyPatch):
        rag = MultiModalRAG(dimension=32)

        def _raise(*args: object, **kwargs: object) -> None:
            msg = "delete failed"
            raise RuntimeError(msg)

        text_coll = _FakeCollection({})
        clip_coll = _FakeCollection({})
        text_coll.delete = _raise  # type: ignore[method-assign]
        clip_coll.delete = _raise  # type: ignore[method-assign]
        monkeypatch.setattr(rag, "_ensure_chroma", lambda: None)
        rag._chroma_text_collection = text_coll
        rag._chroma_clip_collection = clip_coll
        rag._remove_from_chroma(["c1"])

    def test_remove_document_triggers_chroma_delete(self):
        rag = MultiModalRAG(dimension=32)
        rag.index_document(Document(id="d1", text="content to remove"))
        assert rag.remove_document("d1") is True
        assert rag.remove_document("d1") is False


class TestInMemoryFallback:
    def test_search_uses_in_memory_when_chroma_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mmr, "_CHROMA_AVAILABLE", False)
        rag = MultiModalRAG(dimension=32)
        rag.index_document(Document(id="d1", text="Python programming language", metadata={"topic": "code"}))
        results = rag.search("Python", top_k=3)
        assert len(results) >= 1
        assert results[0].citation is not None
        meta = rag.search_by_metadata("Python", {"topic": "code"}, top_k=3)
        assert len(meta) >= 1
        assert rag.search_by_metadata("Python", {"topic": "missing"}) == []

    def test_to_results_skips_non_positive_scores(self):
        rag = MultiModalRAG(dimension=32)
        c = Chunk(id="c1", text="t", document_id="d1", embedding=[-1.0, 0.0])
        scored = [(-0.5, c)]
        assert rag._to_results(scored, 5) == []


class TestCrossModalSearch:
    def test_search_in_memory_clip_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        rag = _make_rag_with_clip(monkeypatch)
        monkeypatch.setattr(rag, "_ensure_chroma", lambda: None)
        rag._chroma_text_collection = None
        rag._chroma_clip_collection = None
        png = tmp_path / "img.png"
        _make_png(png)
        rag.index_document(Document(id="d1", text="text content", images=[str(png)]))
        results = rag.search("content", top_k=5, include_images=True)
        assert any(r.modality == "image" for r in results)

    def test_search_clip_chroma_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        rag = _make_rag_with_clip(monkeypatch)
        png = tmp_path / "img.png"
        _make_png(png)
        rag.index_document(Document(id="d1", text="text", images=[str(png)]))
        results = rag.search("text", top_k=5, include_images=True)
        assert isinstance(results, list)


class TestCitationsAndPersistence:
    def test_get_citations(self):
        rag = MultiModalRAG(dimension=32)
        ids = rag.index_document(Document(id="d1", text="citation content", source="s", page=3))
        citations = rag.get_citations(ids)
        assert len(citations) == len(ids)
        assert all(isinstance(c, Citation) for c in citations)

    def test_get_citations_empty(self):
        rag = MultiModalRAG(dimension=32)
        assert rag.get_citations(["missing"]) == []

    def test_save_index_no_path(self):
        rag = MultiModalRAG(dimension=32)
        rag.save_index()  # no _index_path -> returns silently

    def test_load_index_missing_path(self):
        rag = MultiModalRAG(dimension=32)
        rag.load_index()  # no path -> returns silently
        rag.load_index(Path("no_such_file.json"))  # path not exists -> returns

    def test_save_and_roundtrip_with_images(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        rag = _make_rag_with_clip(monkeypatch)
        png = tmp_path / "img.png"
        _make_png(png)
        rag.index_document(Document(id="d1", text="content", images=[str(png)]))
        path = tmp_path / "index.json"
        rag.save_index(path)
        assert path.exists()
        rag2 = _make_rag_with_clip(monkeypatch)
        rag2.load_index(path)
        assert rag2.get_stats()["documents"] == 1

    async def test_async_save_and_load(self, tmp_path: Path):
        rag = MultiModalRAG(dimension=32)
        rag.index_document(Document(id="d1", text="async content"))
        path = tmp_path / "index.json"
        await rag.async_save_index(path)
        assert path.exists()
        rag2 = MultiModalRAG(dimension=32)
        await rag2.async_load_index(path)
        assert rag2.get_stats()["documents"] == 1


class TestDataClasses:
    def test_defaults(self):
        c = Citation(document_id="d", source="s", page=1, chunk_index=0, timestamp=0.0)
        assert c.modality == "text"
        assert c.image_path == ""
        ch = Chunk(id="c", text="t", document_id="d")
        assert ch.embedding == []
        assert ch.modality == "text"
        r = SearchResult(chunk_id="c", document_id="d", text="t", score=0.5)
        assert r.citation is None
        assert r.metadata == {}
