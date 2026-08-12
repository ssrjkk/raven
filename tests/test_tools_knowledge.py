from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import raven.tools.knowledge as knowledge
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.knowledge import (
    knowledge_add_entity,
    knowledge_add_relation,
    knowledge_extract,
    knowledge_graph_vis,
    knowledge_search,
    knowledge_stats,
    register_knowledge_tools,
)
from raven.unique.knowledge_graph import Document


def _entity(name: str, etype: str, eid: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, type=etype, id=eid)


@pytest.fixture
def kg(tmp_path: Path) -> Generator[MagicMock, None, None]:
    """Reset the module-level graph cache and mock KnowledgeGraph + persistence path."""
    old = knowledge._kg
    knowledge._kg = None
    instance = MagicMock()
    kg_path = tmp_path / "kg" / "knowledge_graph.json"
    with (
        patch("raven.tools.knowledge.KnowledgeGraph", return_value=instance),
        patch("raven.tools.knowledge._KG_PATH", kg_path),
    ):
        yield instance
    knowledge._kg = old


class TestKnowledgeGraphLifecycle:
    def test_get_kg_creates_when_file_missing(self, kg: MagicMock) -> None:
        result = knowledge._get_kg()
        assert result is kg
        kg.load.assert_not_called()

    def test_get_kg_loads_existing_file(self, kg: MagicMock) -> None:
        path = knowledge._KG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"entities": {}}', encoding="utf-8")
        result = knowledge._get_kg()
        assert result is kg
        kg.load.assert_called_once_with(path)

    def test_get_kg_caches_instance(self, kg: MagicMock) -> None:
        created: list[MagicMock] = []

        def _factory() -> MagicMock:
            instance = MagicMock()
            created.append(instance)
            return instance

        with patch("raven.tools.knowledge.KnowledgeGraph", side_effect=_factory):
            first = knowledge._get_kg()
            second = knowledge._get_kg()

        assert first is second
        assert first in created
        assert len(created) == 1

    def test_get_kg_handles_load_failure(self, kg: MagicMock) -> None:
        path = knowledge._KG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("garbage", encoding="utf-8")
        kg.load.side_effect = RuntimeError("corrupt file")
        with patch("raven.tools.knowledge.logger.warning") as warn:
            result = knowledge._get_kg()
        assert result is kg
        warn.assert_called_once()
        kg.load.assert_called_once_with(path)

    def test_save_kg_creates_parent_dir(self, kg: MagicMock) -> None:
        knowledge._save_kg()
        assert knowledge._KG_PATH.parent.exists()
        kg.save.assert_called_once_with(knowledge._KG_PATH)

    def test_save_kg_logs_error(self, kg: MagicMock) -> None:
        kg.save.side_effect = RuntimeError("disk full")
        with patch("raven.tools.knowledge.logger.error") as err:
            knowledge._save_kg()
        err.assert_called_once()
        assert knowledge._KG_PATH.parent.exists()


class TestKnowledgeExtract:
    def test_extract_success(self, kg: MagicMock) -> None:
        kg._entities = {
            "e1": _entity("Alice", "PERSON", "e1"),
            "e2": _entity("Bob", "PERSON", "e2"),
            "e3": _entity("fastapi", "TECHNOLOGY", "e3"),
        }
        kg.extract_from_document.return_value = {
            "entities": ["Alice", "Bob", "fastapi"],
            "relations": ["Alice --calls--> fastapi", "fastapi --uses--> Bob"],
        }
        kg.get_stats.return_value = {"entities": 3, "relations": 2}
        result = knowledge_extract("Alice calls fastapi", source="test.py")

        assert result.startswith("Extracted from test.py")
        assert "- Entities found: 3" in result
        assert "- Relations found: 2" in result
        assert "- Total in graph: 3 entities, 2 relations" in result
        assert "[PERSON] Alice, Bob" in result
        assert "[TECHNOLOGY] fastapi" in result
        assert "Relations:" in result
        assert "  - Alice --calls--> fastapi" in result

        doc_arg = kg.extract_from_document.call_args.args[0]
        assert isinstance(doc_arg, Document)
        assert doc_arg.text == "Alice calls fastapi"
        assert doc_arg.source == "test.py"
        kg.save.assert_called_once_with(knowledge._KG_PATH)

    def test_extract_no_entities(self, kg: MagicMock) -> None:
        kg._entities = {}
        kg.extract_from_document.return_value = {"entities": [], "relations": []}
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        result = knowledge_extract("plain text")
        assert result == "Extracted from text\n- Entities found: 0\n- Relations found: 0\n- Total in graph: 0 entities, 0 relations"
        assert "Relations:" not in result

    def test_extract_groups_and_truncates_types(self, kg: MagicMock) -> None:
        kg._entities = {f"e{i}": _entity(f"n{i}", "PERSON", f"e{i}") for i in range(1, 11)}
        kg._entities["e11"] = _entity("fastapi", "TECHNOLOGY", "e11")
        kg.extract_from_document.return_value = {"entities": [f"n{i}" for i in range(1, 11)], "relations": []}
        kg.get_stats.return_value = {"entities": 11, "relations": 0}
        result = knowledge_extract("text")
        assert "[PERSON] n1, n2, n3, n4, n5, n6, n7, n8..." in result
        assert "[TECHNOLOGY] fastapi" in result
        assert "Relations:" not in result

    def test_extract_error_returns_error(self, kg: MagicMock) -> None:
        kg.extract_from_document.side_effect = RuntimeError("boom")
        result = knowledge_extract("text")
        assert result == "[error] Extraction failed: boom"
        kg.save.assert_not_called()


class TestKnowledgeSearch:
    def test_search_empty_graph(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        result = knowledge_search("anything")
        assert result == "[info] Knowledge graph is empty. Use knowledge_extract to add data."
        kg.search.assert_not_called()

    def test_search_error_returns_error(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 1, "relations": 0}
        kg.search.side_effect = RuntimeError("boom")
        result = knowledge_search("query")
        assert result == "[error] Search failed: boom"

    def test_search_no_results(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 1, "relations": 0}
        kg.search.return_value = []
        result = knowledge_search("missing")
        assert result == "No results found for 'missing'."

    def test_search_with_results_and_neighbors(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 1, "relations": 0}
        neighbors = [{"relation": f"r{i}", "entity": f"e{i}", "type": "T"} for i in range(6)]
        kg.search.return_value = [{"id": "e1", "name": "Alice", "type": "PERSON", "neighbors": neighbors}]
        result = knowledge_search("alice", max_depth=3)

        assert "Knowledge Graph results for 'alice':" in result
        assert "- [PERSON] Alice" in result
        assert "  → r0: e0 (T)" in result
        assert result.count("  → ") == 5
        kg.search.assert_called_once_with("alice", max_depth=3)

    def test_search_result_without_neighbors(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 1, "relations": 0}
        kg.search.return_value = [{"id": "e1", "name": "Alice", "type": "PERSON"}]
        result = knowledge_search("alice")
        assert "- [PERSON] Alice" in result
        assert "  → " not in result


class TestKnowledgeStats:
    def test_stats_with_types(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {
            "entities": 3,
            "relations": 2,
            "entity_types": {"PERSON": 2, "TECHNOLOGY": 1},
            "relation_types": {"calls": 2},
        }
        result = knowledge_stats()
        assert result.startswith("Knowledge Graph Statistics")
        assert "- Total entities: 3" in result
        assert "- Total relations: 2" in result
        assert "Entity types:" in result
        assert "[PERSON] 2" in result
        assert "[TECHNOLOGY] 1" in result
        assert "Relation types:" in result
        assert "[calls] 2" in result

    def test_stats_without_types(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        result = knowledge_stats()
        assert result == "Knowledge Graph Statistics\n- Total entities: 0\n- Total relations: 0"
        assert "Entity types:" not in result
        assert "Relation types:" not in result


class TestKnowledgeAddEntity:
    def test_add_entity_default_metadata(self, kg: MagicMock) -> None:
        kg.add_entity.return_value = SimpleNamespace(name="Flask", type="TECHNOLOGY", id="abc123")
        result = knowledge_add_entity("Flask")
        assert result == "Entity added: [TECHNOLOGY] Flask (id: abc123)"
        kg.add_entity.assert_called_once_with("Flask", "concept", {})
        kg.save.assert_called_once_with(knowledge._KG_PATH)

    def test_add_entity_valid_json_metadata(self, kg: MagicMock) -> None:
        kg.add_entity.return_value = SimpleNamespace(name="X", type="concept", id="id1")
        result = knowledge_add_entity("X", metadata='{"level": "high"}')
        assert result == "Entity added: [concept] X (id: id1)"
        kg.add_entity.assert_called_once_with("X", "concept", {"level": "high"})

    def test_add_entity_invalid_json_metadata(self, kg: MagicMock) -> None:
        kg.add_entity.return_value = SimpleNamespace(name="X", type="concept", id="id1")
        result = knowledge_add_entity("X", metadata="not json")
        assert result == "Entity added: [concept] X (id: id1)"
        kg.add_entity.assert_called_once_with("X", "concept", {"note": "not json"})

    def test_add_entity_error_returns_error(self, kg: MagicMock) -> None:
        kg.add_entity.side_effect = ValueError("duplicate")
        result = knowledge_add_entity("X")
        assert result == "[error] Failed to add entity: duplicate"
        kg.save.assert_not_called()


class TestKnowledgeAddRelation:
    def test_add_relation_missing_source(self, kg: MagicMock) -> None:
        kg._find_entity.side_effect = lambda name: None
        result = knowledge_add_relation("Carol", "Bob")
        assert result == "[error] Source entity 'Carol' not found. Add it first with knowledge_add_entity."
        kg.add_relation.assert_not_called()

    def test_add_relation_missing_target(self, kg: MagicMock) -> None:
        src = _entity("Alice", "PERSON", "e1")

        def _find(name: str) -> Any:
            return src if name == "Alice" else None

        kg._find_entity.side_effect = _find
        result = knowledge_add_relation("Alice", "Carol")
        assert result == "[error] Target entity 'Carol' not found. Add it first with knowledge_add_entity."
        kg.add_relation.assert_not_called()

    def test_add_relation_success(self, kg: MagicMock) -> None:
        src = _entity("Alice", "PERSON", "e1")
        tgt = _entity("Bob", "PERSON", "e2")

        def _find(name: str) -> Any:
            return {"Alice": src, "Bob": tgt}.get(name)

        kg._find_entity.side_effect = _find
        result = knowledge_add_relation("Alice", "Bob", type="knows")
        assert result == "Relation added: Alice --knows--> Bob"
        kg.add_relation.assert_called_once_with("e1", "e2", "knows")
        kg.save.assert_called_once_with(knowledge._KG_PATH)

    def test_add_relation_error_returns_error(self, kg: MagicMock) -> None:
        src = _entity("Alice", "PERSON", "e1")
        tgt = _entity("Bob", "PERSON", "e2")

        def _find(name: str) -> Any:
            return {"Alice": src, "Bob": tgt}.get(name)

        kg._find_entity.side_effect = _find
        kg.add_relation.side_effect = RuntimeError("boom")
        result = knowledge_add_relation("Alice", "Bob")
        assert result == "[error] Failed to add relation: boom"
        kg.save.assert_not_called()


class TestKnowledgeGraphVis:
    def test_graph_vis_empty(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 0, "relations": 0}
        result = knowledge_graph_vis()
        assert result == "[info] Knowledge graph is empty."
        kg.export_vis.assert_not_called()

    def test_graph_vis_data(self, kg: MagicMock) -> None:
        kg.get_stats.return_value = {"entities": 1, "relations": 1}
        kg.export_vis.return_value = {"nodes": [{"id": "e1"}], "links": [{"source": "e1"}]}
        result = knowledge_graph_vis()
        assert "[Graph data: 1 nodes, 1 links]" in result
        assert '```json' in result
        assert '"nodes"' in result


class TestRegisterKnowledgeTools:
    def test_register_knowledge_tools(self) -> None:
        registry = ToolRegistry(policy_store=MagicMock())
        register_knowledge_tools(registry)

        assert registry.count == 6
        specs = registry.list("knowledge")
        names = {spec.name for spec in specs}
        assert names == {
            "knowledge_extract",
            "knowledge_search",
            "knowledge_stats",
            "knowledge_add_entity",
            "knowledge_add_relation",
            "knowledge_graph_vis",
        }
        assert all(spec.category == "knowledge" for spec in specs)

        handlers = {spec.name: spec.handler for spec in specs}
        assert handlers["knowledge_extract"] is knowledge_extract
        assert handlers["knowledge_search"] is knowledge_search
        assert handlers["knowledge_stats"] is knowledge_stats
        assert handlers["knowledge_add_entity"] is knowledge_add_entity
        assert handlers["knowledge_add_relation"] is knowledge_add_relation
        assert handlers["knowledge_graph_vis"] is knowledge_graph_vis
