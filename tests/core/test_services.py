from __future__ import annotations

import json
from pathlib import Path

import pytest

from raven.core.services import Chunk, Chunker, Entity, EntityExtractor, ExtractorResult
from raven.core.services.persister import PersisterBackend, SQLitePersister, get_persister


@pytest.mark.asyncio
class TestEntityExtractor:
    async def test_extract_email(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Contact me at test@example.com")
        emails = [e for e in result.entities if e.label == "EMAIL"]
        assert len(emails) == 1
        assert emails[0].text == "test@example.com"
        assert emails[0].score == 1.0

    async def test_extract_url(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Visit https://example.com/path")
        urls = [e for e in result.entities if e.label == "URL"]
        assert len(urls) == 1
        assert "example.com" in urls[0].text

    async def test_extract_phone(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Call +7 123 456 78 90")
        phones = [e for e in result.entities if e.label == "PHONE"]
        assert len(phones) >= 1

    async def test_extract_date(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Date: 2024-12-25")
        dates = [e for e in result.entities if e.label == "DATE"]
        assert len(dates) == 1
        assert dates[0].text == "2024-12-25"

    async def test_extract_multiple(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Email: a@b.com, url: https://x.com, date: 2024-01-01")
        assert len(result.entities) >= 3

    async def test_extract_empty(self):
        extractor = EntityExtractor()
        result = await extractor.extract("No entities here.")
        assert len(result.entities) == 0

    async def test_extract_with_labels_filter(self):
        extractor = EntityExtractor()
        result = await extractor.extract("Email: a@b.com, date: 2024-01-01", labels=["EMAIL"])
        assert all(e.label == "EMAIL" for e in result.entities)
        assert len(result.entities) == 1

    async def test_extract_result_attributes(self):
        extractor = EntityExtractor()
        result = await extractor.extract("test@example.com")
        assert isinstance(result, ExtractorResult)
        assert "total" in result.raw

    async def test_extract_with_llm_provider(self):
        class MockLLM:
            async def complete(self, messages, **kw):
                return {"choices": [{"message": {"content": "PERSON|Alice\nORG|Acme"}}]}
        extractor = EntityExtractor(llm_provider=MockLLM())
        result = await extractor.extract(
            "Alice works at Acme corporation, a large company in the city of Boston, and manages the engineering team."
        )
        assert len(result.entities) >= 2
        labels = {e.label for e in result.entities}
        assert "PERSON" in labels or "ORG" in labels

    async def test_extract_llm_empty_response(self):
        class MockLLM:
            async def complete(self, messages, **kw):
                return {"choices": [{"message": {"content": ""}}]}
        extractor = EntityExtractor(llm_provider=MockLLM())
        result = await extractor.extract(
            "This is some text that is long enough to trigger the LLM entity extraction path without real entities."
        )
        assert result.entities is not None

    async def test_extract_llm_no_entities(self):
        class MockLLM:
            async def complete(self, messages, **kw):
                return {"choices": [{"message": {"content": "ZZZZ|qqqq"}}]}
        extractor = EntityExtractor(llm_provider=MockLLM())
        result = await extractor.extract(
            "hello world this is a long message with no organizations or people mentioned anywhere inside it"
        )
        assert len(result.entities) == 0  # "qqqq" has no match in the text

    async def test_extract_llm_failure_logged(self):
        class FailingLLM:
            async def complete(self, messages, **kw):
                raise RuntimeError("LLM failed")
        extractor = EntityExtractor(llm_provider=FailingLLM())
        result = await extractor.extract(
            "Contact us at test@example.com for more information about our products and services today."
        )
        assert len(result.entities) == 1  # regex still finds email

    async def test_extract_llm_deduplicates(self):
        class MockLLM:
            async def complete(self, messages, **kw):
                return {"choices": [{"message": {"content": "EMAIL|test@example.com"}}]}
        extractor = EntityExtractor(llm_provider=MockLLM())
        result = await extractor.extract(
            "Please send all invoices to test@example.com, that is the email address our accounting team uses."
        )
        emails = [e for e in result.entities if e.label == "EMAIL"]
        assert len(emails) == 1  # deduplicated

    async def test_extract_llm_skips_short_text(self):
        class MockLLM:
            def __init__(self):
                self.calls = 0

            async def complete(self, messages, **kw):
                self.calls += 1
                return {"choices": [{"message": {"content": "PERSON|Bob"}}]}

        llm = MockLLM()
        extractor = EntityExtractor(llm_provider=llm)
        result = await extractor.extract("Hi Bob")
        assert len(result.entities) == 0  # short text: pattern finds nothing, LLM path gated off
        assert llm.calls == 0

    async def test_extract_llm_no_provider(self):
        extractor = EntityExtractor(llm_provider=None)
        result = await extractor.extract("hello")
        assert len(result.entities) == 0

    async def test_extract_llm_direct_without_provider(self):
        extractor = EntityExtractor(llm_provider=None)
        result = await extractor._extract_llm("text", labels=None)
        assert len(result) == 0


class TestChunker:
    def test_semantic_chunk(self):
        chunker = Chunker(max_chars=200, overlap=0)
        text = "Para one.\n\nPara two.\n\nPara three."
        result = chunker.chunk(text, strategy="semantic")
        assert len(result.chunks) >= 1
        assert result.strategy == "semantic"

    def test_fixed_chunk(self):
        chunker = Chunker(max_chars=150, overlap=0)
        text = "a" * 500
        result = chunker.chunk(text, strategy="fixed")
        assert len(result.chunks) >= 3
        assert all(len(c.text) <= 150 for c in result.chunks)

    def test_sliding_chunk(self):
        chunker = Chunker(max_chars=150, overlap=30)
        text = "a" * 500
        result = chunker.chunk(text, strategy="sliding")
        assert len(result.chunks) >= 3

    def test_invalid_strategy_fallback(self):
        chunker = Chunker()
        result = chunker.chunk("Hello world.", strategy="invalid")
        assert result.strategy == "semantic"

    def test_empty_text(self):
        chunker = Chunker()
        result = chunker.chunk("")
        assert len(result.chunks) == 0

    def test_chunk_attributes(self):
        chunker = Chunker()
        result = chunker.chunk("Hello.\n\nWorld.", metadata={"source": "test"})
        assert len(result.chunks) >= 1
        assert isinstance(result.chunks[0], Chunk)
        assert result.chunks[0].index >= 0

    def test_overlap_clamp(self):
        chunker = Chunker(max_chars=200, overlap=300)
        assert chunker.overlap == 200

    def test_max_chars_minimum(self):
        chunker = Chunker(max_chars=10, overlap=0)
        assert chunker.max_chars >= 100


@pytest.mark.asyncio
class TestSQLitePersister:
    async def test_insert_and_get(self, tmp_path):
        db_path = tmp_path / "test.db"
        p: PersisterBackend = SQLitePersister(db_path)
        id = await p.insert("test_col", {"key": "value"})
        assert id is not None
        assert len(id) > 0
        retrieved = await p.get("test_col", id)
        assert retrieved is not None
        assert retrieved["key"] == "value"
        await p.close()

    async def test_get_nonexistent(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        result = await p.get("test_col", "nonexistent")
        assert result is None
        await p.close()

    async def test_search(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        await p.insert("test_col", {"content": "hello world"})
        await p.insert("test_col", {"content": "goodbye world"})
        results = await p.search("test_col", "hello")
        assert len(results) >= 1
        await p.close()

    async def test_delete(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        id = await p.insert("test_col", {"data": "to_delete"})
        assert await p.delete("test_col", id) is True
        assert await p.get("test_col", id) is None
        await p.close()

    async def test_delete_nonexistent(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        assert await p.delete("test_col", "no_such_id") is False
        await p.close()

    async def test_unknown_columns_in_search(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        await p.insert("other_col", {"x": 1, "y": 2})
        results = await p.search("other_col", "1")
        assert isinstance(results, list)
        await p.close()

    async def test_insert_with_complex_data(self, tmp_path):
        p: PersisterBackend = SQLitePersister(tmp_path / "test.db")
        complex_data = {"list": [1, 2, 3], "nested": {"a": 1}, "number": 42, "none": None}
        id = await p.insert("complex", complex_data)
        retrieved = await p.get("complex", id)
        assert retrieved is not None
        assert retrieved["list"] == [1, 2, 3]
        await p.close()

    async def test_get_persister_singleton(self, tmp_path):
        import raven.core.services.persister as pm
        get_persister(str(tmp_path / "singleton.db"))
        get_persister(str(tmp_path / "singleton.db"))
        old = pm._backend
        pm._backend = None
        fresh = get_persister(str(tmp_path / "fresh.db"))
        assert fresh is not None
        pm._backend = old


class TestChunkerEdgeCases:
    def test_stride_minimum(self):
        chunker = Chunker(max_chars=100, overlap=100)
        text = "a" * 500
        result = chunker.chunk(text, strategy="sliding")
        assert len(result.chunks) == 500  # stride=1, each chunk has varying length 100..1
        assert result.chunks[0].text == "a" * 100
    def test_semantic_chunk_overlap(self):
        chunker = Chunker(max_chars=200, overlap=50)
        paras = "\n\n".join([f"Paragraph number {i} with some content." for i in range(10)])
        result = chunker.chunk(paras, strategy="semantic")
        assert len(result.chunks) >= 1
        total_in_chunks = sum(len(c.text) for c in result.chunks)
        assert total_in_chunks > 0

    def test_fixed_chunk_boundary(self):
        chunker = Chunker(max_chars=100, overlap=0)
        text = "a" * 500
        result = chunker.chunk(text, strategy="fixed")
        assert len(result.chunks) == 5
        assert all(len(c.text) <= 100 for c in result.chunks)

    def test_sliding_chunk_content(self):
        chunker = Chunker(max_chars=150, overlap=30)
        text = "a" * 400
        result = chunker.chunk(text, strategy="sliding")
        assert len(result.chunks) >= 2

    def test_chunker_result_type(self):
        chunker = Chunker()
        result = chunker.chunk("test")
        assert result.total_tokens > 0
        assert isinstance(result.chunks, list)
