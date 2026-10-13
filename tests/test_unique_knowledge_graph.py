from __future__ import annotations

from types import SimpleNamespace

import pytest

from raven.unique import knowledge_graph as kg_mod
from raven.unique.knowledge_graph import Document, Entity, KnowledgeGraph, Relation


class TestKnowledgeGraph:
    def setup_method(self) -> None:
        self.kg = KnowledgeGraph()

    def test_add_entity(self):
        entity = self.kg.add_entity("Python", "language")
        assert entity.name == "Python"
        assert entity.type == "language"
        assert entity.id != ""

    def test_add_entity_dedup(self):
        e1 = self.kg.add_entity("Python", "language")
        e2 = self.kg.add_entity("python", "language")
        assert e1.id == e2.id

    def test_add_relation(self):
        s = self.kg.add_entity("Alice", "person")
        t = self.kg.add_entity("Bob", "person")
        rel = self.kg.add_relation(s.id, t.id, "knows")
        assert rel.rel_type == "knows"
        assert rel.source_id == s.id
        assert rel.target_id == t.id

    def test_add_relation_invalid(self):
        import pytest
        with pytest.raises(ValueError):
            self.kg.add_relation("nonexistent", "also", "invalid")

    def test_extract_entities_from_document(self):
        doc = Document(text="Alice Smith uses Python and Docker. "
                            "John Doe imports flask.")
        result = self.kg.extract_from_document(doc)
        assert len(result["entities"]) >= 3
        assert any("Alice" in e for e in result["entities"])

    def test_extract_tech_entities(self):
        doc = Document(text="We use PostgreSQL and Redis for storage, "
                            "and deploy with Docker and Kubernetes.")
        result = self.kg.extract_from_document(doc)
        tech_names = [e.lower() for e in result["entities"]]
        assert "postgresql" in tech_names
        assert "docker" in tech_names

    def test_search(self):
        s = self.kg.add_entity("Flask", "framework")
        t = self.kg.add_entity("Python", "language")
        self.kg.add_relation(s.id, t.id, "uses")
        results = self.kg.search("Flask", max_depth=2)
        assert len(results) >= 1
        assert any(r["name"] == "Flask" for r in results)

    def test_search_no_match(self):
        self.kg.add_entity("Python", "language")
        results = self.kg.search("NonexistentThing")
        assert results == []

    def test_get_entity(self):
        e = self.kg.add_entity("Test", "test")
        assert self.kg.get_entity(e.id) is not None
        assert self.kg.get_entity("nonexistent") is None

    def test_get_relations(self):
        s = self.kg.add_entity("A", "type")
        t = self.kg.add_entity("B", "type")
        self.kg.add_relation(s.id, t.id, "connects")
        rels = self.kg.get_relations(s.id)
        assert len(rels) >= 1

    def test_get_stats(self):
        self.kg.add_entity("Python", "language")
        self.kg.add_entity("Docker", "tool")
        self.kg.add_entity("Flask", "framework")
        s = self.kg.add_entity("A", "type")
        t = self.kg.add_entity("B", "type")
        self.kg.add_relation(s.id, t.id, "connects")
        stats = self.kg.get_stats()
        assert stats["entities"] == 5
        assert stats["relations"] == 1

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "kg.json"
        self.kg.add_entity("Python", "language")
        self.kg.save(str(path))
        assert path.exists()

        kg2 = KnowledgeGraph()
        kg2.load(str(path))
        assert kg2.get_stats()["entities"] == 1


class TestRegexRelations:
    def setup_method(self) -> None:
        self.kg = KnowledgeGraph()

    def test_regex_relation_between_entities(self) -> None:
        # "alpha calls beta" -> module entities alpha/beta, then the "calls" relation connects them
        result = self.kg.extract_from_document(Document(text="alpha calls beta"))
        assert any("alpha" in r and "beta" in r for r in result["relations"])
        assert any(r.rel_type == "calls" for r in self.kg._relations)


class TestSearchBfs:
    def setup_method(self) -> None:
        self.kg = KnowledgeGraph()

    def test_visited_shortcut_and_export_vis(self) -> None:
        a = self.kg.add_entity("alpha", "node")
        b = self.kg.add_entity("beta", "node")
        c = self.kg.add_entity("gamma", "node")
        d = self.kg.add_entity("delta", "node")
        self.kg.add_relation(a.id, b.id, "to")
        self.kg.add_relation(a.id, c.id, "to")
        self.kg.add_relation(b.id, d.id, "to")
        self.kg.add_relation(c.id, d.id, "to")
        # delta reachable via beta and gamma -> BFS revisit hits the `visited` continue branch
        results = self.kg.search("alpha", max_depth=2)
        names = {r["name"] for r in results}
        assert names == {"alpha", "beta", "gamma", "delta"}
        vis = self.kg.export_vis()
        assert len(vis["nodes"]) == 4
        assert len(vis["links"]) == 4

    def test_bfs_skips_dangling_neighbor(self, tmp_path) -> None:
        # a saved graph with a relation pointing to a missing entity -> load builds a dangling edge
        import json

        data = {
            "entities": {"e1": {"id": "e1", "name": "alpha", "type": "node", "metadata": {}}},
            "relations": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "ghost",
                    "rel_type": "to",
                    "metadata": {},
                }
            ],
        }
        path = tmp_path / "kg.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        kg = KnowledgeGraph()
        kg.load(str(path))
        results = kg.search("alpha", max_depth=2)
        assert [r["id"] for r in results] == ["e1"]


class TestSpacyPath:
    def test_lazy_spacy_returns_none_when_unavailable(self) -> None:
        assert kg_mod._SPACY_AVAILABLE is False
        assert kg_mod._lazy_spacy() is None

    def test_lazy_spacy_loads_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(kg_mod, "_SPACY_AVAILABLE", True)
        monkeypatch.setattr(kg_mod, "spacy", SimpleNamespace(load=lambda _name: "MODEL"), raising=False)
        monkeypatch.setattr(kg_mod._lazy_spacy, "_model", None, raising=False)
        assert kg_mod._lazy_spacy() == "MODEL"
        # second call uses the cached attribute
        assert kg_mod._lazy_spacy() == "MODEL"

    def test_lazy_spacy_model_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_name: str) -> None:
            raise OSError("model not found")

        monkeypatch.setattr(kg_mod, "_SPACY_AVAILABLE", True)
        monkeypatch.setattr(kg_mod, "spacy", SimpleNamespace(load=_raise), raising=False)
        monkeypatch.setattr(kg_mod._lazy_spacy, "_model", None, raising=False)
        assert kg_mod._lazy_spacy() is None

    def test_extract_with_spacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Tok:
            def __init__(self, i: int, text: str, dep_: str, head: _Tok | None = None) -> None:
                self.i = i
                self.text = text
                self.dep_ = dep_
                self.head = head or self
                self.children: list[_Tok] = []

            @property
            def subtree(self) -> list[_Tok]:
                return self.children or [self]

        class _Ent:
            def __init__(self, text: str, label_: str, start: int, end: int) -> None:
                self.text = text
                self.label_ = label_
                self.start = start
                self.end = end

        alice = _Tok(0, "Alice", "ROOT")
        bob = _Tok(2, "Bob", "dobj", head=alice)
        park = _Tok(5, "park", "nmod", head=alice)
        alice.children = [alice, bob, park]

        class _Doc:
            def __init__(self) -> None:
                self.ents = [_Ent("Alice", "PERSON", 0, 1), _Ent("Bob", "PERSON", 2, 3)]
                self.sents = [SimpleNamespace(root=alice)]

        class _Nlp:
            def __call__(self, _text: str) -> _Doc:
                return _Doc()

        monkeypatch.setattr(kg_mod, "_SPACY_AVAILABLE", True)
        monkeypatch.setattr(kg_mod, "spacy", SimpleNamespace(load=lambda _name: _Nlp()), raising=False)
        monkeypatch.setattr(kg_mod._lazy_spacy, "_model", None, raising=False)

        kg = KnowledgeGraph()
        result = kg.extract_from_document(Document(text="Alice gave the book to Bob in the park"))
        assert any(r.rel_type == "acts_on" for r in kg._relations)
        assert kg._find_entity("Alice") is not None
        assert "Alice --acts_on--> Bob" in result["relations"]
