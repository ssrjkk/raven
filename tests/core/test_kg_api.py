from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.kg_api as kga
from raven.unique.knowledge_graph import KnowledgeGraph


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    kg_path = tmp_path / "kg.json"
    monkeypatch.setattr(kga, "_KG_PATH", kg_path)
    app = FastAPI()
    app.include_router(kga.create_knowledge_router())
    return TestClient(app), kg_path


def test_extract_success(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post("/api/knowledge/extract", params={"text": "Alice and Bob work on the Raven project."})
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    assert "stats" in body


def test_extract_with_source(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/knowledge/extract",
        params={"text": "FastAPI is built on Starlette.", "source": "docs"},
    )
    assert resp.status_code == 200
    assert resp.json()["stats"]["entities"] >= 1


def test_extract_error(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client

    def boom(self: KnowledgeGraph, document: object) -> dict[str, list[str]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(KnowledgeGraph, "extract_from_document", boom)
    resp = c.post("/api/knowledge/extract", params={"text": "x"})
    assert resp.status_code == 500
    assert "boom" in resp.json()["detail"]


def test_search_empty_kg(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post("/api/knowledge/search", params={"query": "raven"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["stats"]["entities"] == 0


def test_search_success(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Raven", "type": "project"})
    resp = c.post("/api/knowledge/search", params={"query": "raven", "max_depth": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["results"], list)
    assert body["stats"]["entities"] == 1


def test_search_error(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Raven", "type": "project"})

    def boom(self: KnowledgeGraph, query: str, max_depth: int) -> list[dict[str, object]]:
        raise RuntimeError("search boom")

    monkeypatch.setattr(KnowledgeGraph, "search", boom)
    resp = c.post("/api/knowledge/search", params={"query": "raven"})
    assert resp.status_code == 500
    assert "search boom" in resp.json()["detail"]


def test_stats(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Raven"})
    resp = c.get("/api/knowledge/stats")
    assert resp.status_code == 200
    assert resp.json()["entities"] == 1


def test_vis(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Raven"})
    resp = c.get("/api/knowledge/vis")
    assert resp.status_code == 200
    body = resp.json()
    assert "graph" in body
    assert "stats" in body


def test_load_failure_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kg_path = tmp_path / "kg.json"
    kg_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(kga, "_KG_PATH", kg_path)
    app = FastAPI()
    app.include_router(kga.create_knowledge_router())
    c = TestClient(app)
    resp = c.post("/api/knowledge/search", params={"query": "x"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_add_entity_json_metadata(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/knowledge/entity",
        params={"name": "Raven", "type": "project", "metadata": '{"language": "python"}'},
    )
    assert resp.status_code == 200
    body = resp.json()["entity"]
    assert body["name"] == "Raven"
    assert body["type"] == "project"


def test_add_entity_bad_metadata(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/knowledge/entity",
        params={"name": "Raven", "type": "project", "metadata": "not json"},
    )
    assert resp.status_code == 200
    assert resp.json()["entity"]["name"] == "Raven"


def test_add_entity_default_type(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post("/api/knowledge/entity", params={"name": "Raven"})
    assert resp.status_code == 200
    assert resp.json()["entity"]["type"] == "concept"


def test_add_entity_error(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client

    def boom(self: KnowledgeGraph, name: str, ent_type: str, metadata: object) -> object:
        raise RuntimeError("entity boom")

    monkeypatch.setattr(KnowledgeGraph, "add_entity", boom)
    resp = c.post("/api/knowledge/entity", params={"name": "Raven"})
    assert resp.status_code == 500
    assert "entity boom" in resp.json()["detail"]


def test_add_relation_success(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Alice"})
    c.post("/api/knowledge/entity", params={"name": "Bob"})
    resp = c.post("/api/knowledge/relation", params={"source": "Alice", "target": "Bob", "type": "works_with"})
    assert resp.status_code == 200
    rel = resp.json()["relation"]
    assert rel["source"] == "Alice"
    assert rel["target"] == "Bob"
    assert rel["type"] == "works_with"


def test_add_relation_missing_source(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post("/api/knowledge/relation", params={"source": "Nope", "target": "Bob"})
    assert resp.status_code == 404
    assert "Source entity" in resp.json()["detail"]


def test_add_relation_missing_target(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Alice"})
    resp = c.post("/api/knowledge/relation", params={"source": "Alice", "target": "Nope"})
    assert resp.status_code == 404
    assert "Target entity" in resp.json()["detail"]


def test_add_relation_value_error(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Alice"})
    c.post("/api/knowledge/entity", params={"name": "Bob"})

    def boom(self: KnowledgeGraph, sid: str, tid: str, rt: str, metadata: object = None) -> object:
        raise ValueError("duplicate relation")

    monkeypatch.setattr(KnowledgeGraph, "add_relation", boom)
    resp = c.post("/api/knowledge/relation", params={"source": "Alice", "target": "Bob"})
    assert resp.status_code == 400
    assert "duplicate relation" in resp.json()["detail"]


def test_add_relation_generic_error(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    c.post("/api/knowledge/entity", params={"name": "Alice"})
    c.post("/api/knowledge/entity", params={"name": "Bob"})

    def boom(self: KnowledgeGraph, sid: str, tid: str, rt: str, metadata: object = None) -> object:
        raise RuntimeError("rel boom")

    monkeypatch.setattr(KnowledgeGraph, "add_relation", boom)
    resp = c.post("/api/knowledge/relation", params={"source": "Alice", "target": "Bob"})
    assert resp.status_code == 500
    assert "rel boom" in resp.json()["detail"]
