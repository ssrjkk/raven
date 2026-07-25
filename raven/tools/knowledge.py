from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.knowledge_graph import Document, KnowledgeGraph

_kg: KnowledgeGraph | None = None
_KG_PATH = Path(__file__).parent.parent / "data" / "knowledge_graph.json"


def _get_kg() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
        if _KG_PATH.exists():
            try:
                _kg.load(_KG_PATH)
            except Exception as e:
                logger.warning("Failed to load knowledge graph from {}: {}", _KG_PATH, e)
    return _kg


def _save_kg() -> None:
    _KG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        _get_kg().save(_KG_PATH)
    except Exception as e:
        logger.error("Failed to save knowledge graph: {}", e)


def knowledge_extract(text: str, source: str = "") -> str:
    kg = _get_kg()
    doc = Document(text=text, source=source)
    try:
        result = kg.extract_from_document(doc)
        _save_kg()
    except Exception as e:
        logger.error("Knowledge extraction failed: {}", e)
        return f"[error] Extraction failed: {e}"

    entities = result.get("entities", [])
    relations = result.get("relations", [])
    stats = kg.get_stats()
    lines = [
        f"Extracted from {source or 'text'}",
        f"- Entities found: {len(entities)}",
        f"- Relations found: {len(relations)}",
        f"- Total in graph: {stats['entities']} entities, {stats['relations']} relations",
    ]
    if entities:
        by_type: dict[str, list[str]] = {}
        for eid in kg._entities:
            ent = kg._entities[eid]
            by_type.setdefault(ent.type, []).append(ent.name)
        for etype, names in sorted(by_type.items()):
            lines.append(f"  [{etype}] {', '.join(names[:8])}{'...' if len(names) > 8 else ''}")
    if relations:
        lines.append("")
        lines.append("Relations:")
        for r in result.get("relations", [])[:15]:
            lines.append(f"  - {r}")
    return "\n".join(lines)


def knowledge_search(query: str, max_depth: int = 2) -> str:
    kg = _get_kg()
    stats = kg.get_stats()
    if stats["entities"] == 0:
        return "[info] Knowledge graph is empty. Use knowledge_extract to add data."
    try:
        results = kg.search(query, max_depth=max_depth)
    except Exception as e:
        logger.error("Knowledge search failed: {}", e)
        return f"[error] Search failed: {e}"

    if not results:
        return f"No results found for '{query}'."

    lines = [f"Knowledge Graph results for '{query}':\n"]
    for r in results:
        lines.append(f"- [{r['type']}] {r['name']}")
        if r.get("neighbors"):
            for n in r["neighbors"][:5]:
                lines.append(f"  → {n['relation']}: {n['entity']} ({n['type']})")
        lines.append("")
    return "\n".join(lines)


def knowledge_stats() -> str:
    kg = _get_kg()
    stats = kg.get_stats()
    lines = [
        "Knowledge Graph Statistics",
        f"- Total entities: {stats['entities']}",
        f"- Total relations: {stats['relations']}",
    ]
    if stats.get("entity_types"):
        lines.append("")
        lines.append("Entity types:")
        for etype, count in sorted(stats["entity_types"].items(), key=lambda x: -x[1]):
            lines.append(f"  [{etype}] {count}")
    if stats.get("relation_types"):
        lines.append("")
        lines.append("Relation types:")
        for rtype, count in sorted(stats["relation_types"].items(), key=lambda x: -x[1]):
            lines.append(f"  [{rtype}] {count}")
    return "\n".join(lines)


def knowledge_add_entity(name: str, type: str = "concept", metadata: str = "") -> str:
    kg = _get_kg()
    meta: dict[str, Any] = {}
    if metadata:
        try:
            import json

            meta = json.loads(metadata)
        except json.JSONDecodeError:
            meta = {"note": metadata}
    try:
        entity = kg.add_entity(name, type, meta)
        _save_kg()
        return f"Entity added: [{entity.type}] {entity.name} (id: {entity.id})"
    except Exception as e:
        return f"[error] Failed to add entity: {e}"


def knowledge_add_relation(source: str, target: str, type: str = "related_to") -> str:
    kg = _get_kg()
    source_ent = kg._find_entity(source)
    target_ent = kg._find_entity(target)
    if not source_ent:
        return f"[error] Source entity '{source}' not found. Add it first with knowledge_add_entity."
    if not target_ent:
        return f"[error] Target entity '{target}' not found. Add it first with knowledge_add_entity."
    try:
        kg.add_relation(source_ent.id, target_ent.id, type)
        _save_kg()
        return f"Relation added: {source_ent.name} --{type}--> {target_ent.name}"
    except Exception as e:
        return f"[error] Failed to add relation: {e}"


def knowledge_graph_vis() -> str:
    kg = _get_kg()
    stats = kg.get_stats()
    if stats["entities"] == 0:
        return "[info] Knowledge graph is empty."
    data = kg.export_vis()
    import json

    return f"[Graph data: {len(data['nodes'])} nodes, {len(data['links'])} links]\n```json\n{json.dumps(data, indent=2)[:3000]}\n```"


def register_knowledge_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="knowledge_extract",
            description="Extract entities and relations from text and add them to the knowledge graph",
            parameters={
                "text": {"type": "string", "description": "Text to analyze", "required": True},
                "source": {"type": "string", "description": "Source label for the text", "required": False},
            },
            handler=knowledge_extract,
            category="knowledge",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="knowledge_search",
            description="Search the knowledge graph for entities and their relationships",
            parameters={
                "query": {"type": "string", "description": "Search query", "required": True},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "required": False},
            },
            handler=knowledge_search,
            category="knowledge",
            timeout=15,
        )
    )
    registry.register(
        ToolSpec(
            name="knowledge_stats",
            description="Get statistics about the knowledge graph",
            parameters={},
            handler=knowledge_stats,
            category="knowledge",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="knowledge_add_entity",
            description="Manually add an entity to the knowledge graph",
            parameters={
                "name": {"type": "string", "description": "Entity name", "required": True},
                "type": {"type": "string", "description": "Entity type", "required": False},
                "metadata": {"type": "string", "description": "JSON metadata string", "required": False},
            },
            handler=knowledge_add_entity,
            category="knowledge",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="knowledge_add_relation",
            description="Manually add a relation between two entities in the knowledge graph",
            parameters={
                "source": {"type": "string", "description": "Source entity name", "required": True},
                "target": {"type": "string", "description": "Target entity name", "required": True},
                "type": {"type": "string", "description": "Relation type", "required": False},
            },
            handler=knowledge_add_relation,
            category="knowledge",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="knowledge_graph_vis",
            description="Export the knowledge graph as JSON for visualization",
            parameters={},
            handler=knowledge_graph_vis,
            category="knowledge",
            timeout=10,
        )
    )
