from __future__ import annotations

from raven.unique.multi_modal_rag import Document, MultiModalRAG, SearchResult


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
