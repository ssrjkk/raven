from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    with patch("raven.core.kg_api._KG_PATH") as mock_path:
        mock_path.exists.return_value = False
        from raven.core.kg_api import create_knowledge_router
        app.include_router(create_knowledge_router())
    return TestClient(app)


def test_extract(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get, patch("raven.core.kg_api._save_kg") as mock_save:
        kg = MagicMock()
        entity = MagicMock()
        entity.id = "e1"
        entity.name = "Python"
        entity.type = "technology"
        kg.extract_from_document.return_value = [entity]
        kg.get_stats.return_value = {"entities": 1, "relations": 0}
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/extract", params={"text": "Python is great"})
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "stats" in data


def test_search_empty(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get:
        kg = MagicMock()
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/search", params={"query": "Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []


def test_search_with_results(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get:
        kg = MagicMock()
        kg.get_stats.return_value = {"entities": 5, "relations": 3}
        kg.search.return_value = [{"entity": "Python", "score": 0.9}]
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/search", params={"query": "Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1


def test_stats(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get:
        kg = MagicMock()
        kg.get_stats.return_value = {"entities": 100, "relations": 200}
        mock_get.return_value = kg

        resp = client.get("/api/knowledge/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities"] == 100


def test_vis(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get:
        kg = MagicMock()
        kg.export_vis.return_value = {"nodes": [], "edges": []}
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        mock_get.return_value = kg

        resp = client.get("/api/knowledge/vis")
        assert resp.status_code == 200
        data = resp.json()
        assert "graph" in data


def test_add_entity(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get, patch("raven.core.kg_api._save_kg"):
        kg = MagicMock()
        entity = MagicMock()
        entity.id = "e1"
        entity.name = "Python"
        entity.type = "technology"
        kg.add_entity.return_value = entity
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/entity", params={"name": "Python", "type": "technology"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity"]["name"] == "Python"


def test_add_relation(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get, patch("raven.core.kg_api._save_kg"):
        kg = MagicMock()
        source_ent = MagicMock()
        source_ent.id = "e1"
        source_ent.name = "Python"
        target_ent = MagicMock()
        target_ent.id = "e2"
        target_ent.name = "Programming"
        kg._find_entity.side_effect = lambda name: source_ent if name == "Python" else target_ent
        rel = MagicMock()
        rel.id = "r1"
        rel.rel_type = "is_a"
        kg.add_relation.return_value = rel
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/relation", params={"source": "Python", "target": "Programming", "type": "is_a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["relation"]["source"] == "Python"


def test_add_relation_source_not_found(client: TestClient) -> None:
    with patch("raven.core.kg_api._get_kg") as mock_get:
        kg = MagicMock()
        kg._find_entity.return_value = None
        mock_get.return_value = kg

        resp = client.post("/api/knowledge/relation", params={"source": "Unknown", "target": "Python"})
        assert resp.status_code == 404
