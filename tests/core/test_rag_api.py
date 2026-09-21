from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    with patch("raven.core.rag_api._RAG_PATH") as mock_path:
        mock_path.exists.return_value = False
        mock_path.parent = MagicMock()
        from raven.core.rag_api import create_rag_router
        app.include_router(create_rag_router())
    return TestClient(app)


def test_index(client: TestClient) -> None:
    with patch("raven.core.rag_api._get_rag") as mock_get, patch("raven.core.rag_api._save_rag"):
        rag = MagicMock()
        rag.index_document.return_value = ["c1", "c2", "c3"]
        mock_get.return_value = rag

        resp = client.post(
            "/api/rag/index",
            json={"document_id": "d1", "text": "test document"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "d1"
        assert data["chunks"] == 3


def test_search(client: TestClient) -> None:
    with patch("raven.core.rag_api._get_rag") as mock_get:
        rag = MagicMock()
        result = MagicMock()
        result.chunk_id = "c1"
        result.document_id = "d1"
        result.text = "matching text"
        result.score = 0.9
        result.modality = "text"
        result.image_path = None
        result.citation = None
        rag.search.return_value = [result]
        mock_get.return_value = rag

        resp = client.post("/api/rag/search", json={"query": "test", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["score"] == 0.9


def test_stats(client: TestClient) -> None:
    with patch("raven.core.rag_api._get_rag") as mock_get:
        rag = MagicMock()
        rag.get_stats.return_value = {"documents": 10, "chunks": 100}
        mock_get.return_value = rag

        resp = client.get("/api/rag/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"] == 10


def test_remove(client: TestClient) -> None:
    with patch("raven.core.rag_api._get_rag") as mock_get, patch("raven.core.rag_api._save_rag"):
        rag = MagicMock()
        rag.remove_document.return_value = True
        mock_get.return_value = rag

        resp = client.post("/api/rag/remove", json={"document_id": "d1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


def test_remove_not_found(client: TestClient) -> None:
    with patch("raven.core.rag_api._get_rag") as mock_get:
        rag = MagicMock()
        rag.remove_document.return_value = False
        mock_get.return_value = rag

        resp = client.post("/api/rag/remove", json={"document_id": "unknown"})
        assert resp.status_code == 404
