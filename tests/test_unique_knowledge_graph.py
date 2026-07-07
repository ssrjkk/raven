from __future__ import annotations

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
