from __future__ import annotations

import importlib

import pytest

from raven.unique.multi_modal_rag import Document, MultiModalRAG

_HAS_ST = importlib.util.find_spec("sentence_transformers") is not None


class TestMetricsRagAccuracy:
    def setup_method(self) -> None:
        self.rag = MultiModalRAG(dimension=64)
        docs = [
            Document(
                id="d1",
                text="Python is a high-level programming language known for its readability. "
                "It supports multiple programming paradigms including procedural, object-oriented, "
                "and functional programming. Python's dynamic typing and automatic memory management "
                "make it popular for beginners and experts alike.",
                source="python_intro.txt",
            ),
            Document(
                id="d2",
                text="Docker is a containerization platform that packages applications and their "
                "dependencies into lightweight containers. Containers are isolated from each other "
                "and bundle their own software, libraries, and configuration files.",
                source="docker_overview.txt",
            ),
            Document(
                id="d3",
                text="PostgreSQL is a powerful open-source relational database management system "
                "with over 30 years of active development. It supports ACID transactions, "
                "complex queries, foreign keys, triggers, and user-defined functions.",
                source="postgresql_guide.txt",
            ),
            Document(
                id="d4",
                text="Machine learning is a subset of artificial intelligence that enables systems "
                "to learn and improve from experience without being explicitly programmed. "
                "It focuses on developing computer programs that can access data and use it to learn.",
                source="ml_basics.txt",
            ),
            Document(
                id="d5",
                text="Rust is a systems programming language focused on safety, speed, and "
                "concurrency. It guarantees memory safety without a garbage collector by using "
                "a borrow checker and ownership model.",
                source="rust_intro.txt",
            ),
            Document(
                id="d6",
                text="React is a JavaScript library for building user interfaces. It allows "
                "developers to create reusable UI components and manage application state "
                "efficiently through a virtual DOM.",
                source="react_overview.txt",
            ),
            Document(
                id="d7",
                text="Kubernetes is an open-source container orchestration platform that automates "
                "deployment, scaling, and management of containerized applications. It groups "
                "containers into pods for optimal resource utilization.",
                source="k8s_overview.txt",
            ),
            Document(
                id="d8",
                text="Redis is an in-memory data structure store used as a database, cache, "
                "and message broker. It supports data structures such as strings, hashes, "
                "lists, sets, sorted sets, and more.",
                source="redis_intro.txt",
            ),
        ]
        for doc in docs:
            self.rag.index_document(doc, chunk_size=300)

    def test_rag_accuracy_with_sentence_transformer(self) -> None:
        if not _HAS_ST:
            msg = "sentence-transformers not installed, skipping accuracy test"
            pytest.skip(msg)
        queries_expected = [
            ("programming language dynamic typing", "d1"),
            ("python beginner friendly interpreted", "d1"),
            ("containerize application dependencies", "d2"),
            ("docker container isolation", "d2"),
            ("relational database ACID transactions", "d3"),
            ("postgresql queries triggers", "d3"),
            ("machine learning artificial intelligence", "d4"),
            ("systems programming memory safety", "d5"),
            ("rust ownership borrow checker", "d5"),
            ("JavaScript UI components virtual DOM", "d6"),
            ("container orchestration deployment scaling", "d7"),
            ("in-memory cache data structures", "d8"),
            ("redis strings hashes sorted sets", "d8"),
        ]
        correct = 0
        for query, expected_doc_id in queries_expected:
            results = self.rag.search(query, top_k=3)
            match = any(r.document_id == expected_doc_id for r in results)
            if match:
                correct += 1
        accuracy = correct / len(queries_expected)
        assert accuracy >= 0.95

    def test_rag_search_returns_results_even_without_st(self) -> None:
        for query in ("python", "docker", "database", "redis"):
            results = self.rag.search(query, top_k=3)
            assert len(results) >= 1
            assert all(isinstance(r, object) for r in results)
