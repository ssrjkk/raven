from __future__ import annotations

import json
import re
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import spacy
    from spacy.tokens import Doc

    _SPACY_AVAILABLE = True
except ImportError:
    _SPACY_AVAILABLE = False


@dataclass
class Entity:
    id: str
    name: str
    type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    id: str
    source_id: str
    target_id: str
    rel_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    text: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


_ENTITY_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("PERSON", [re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")]),
    ("EMAIL", [re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")]),
    ("URL", [re.compile(r"https?://[^\s]+")]),
    ("VERSION", [re.compile(r"\b\d+\.\d+\.\d+\b")]),
    ("FILE_PATH", [re.compile(r'["\']([^"\']+\.[a-z]+)["\']')]),
    ("module", [re.compile(r"\b[a-z_]+(?:\.[a-z_]+)*\b")]),
    ("class", [re.compile(r"\bclass (\w+)")]),
    ("function", [re.compile(r"\b(def|async def) (\w+)")]),
]

_RELATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("calls", re.compile(r"(\w+) (?:calls|invokes|runs) (\w+)")),
    ("imports", re.compile(r"(?:import|from) (\w+)(?:\.\w+)*")),
    ("uses", re.compile(r"(\w+) (?:uses|depends on|requires) (\w+)")),
    ("contains", re.compile(r"(\w+) (?:contains|has|includes) (\w+)")),
    ("defines", re.compile(r"(\w+) (?:defines|declares|creates) (\w+)")),
]

_TECH_KEYWORDS: dict[str, list[str]] = {
    "TECHNOLOGY": ["flask", "django", "fastapi", "react", "vue", "spring", "rails", "express", "docker", "kubernetes", "git", "npm", "pip", "yarn", "webpack", "vite", "postgresql", "mysql", "sqlite", "mongodb", "redis", "elasticsearch", "python", "javascript", "typescript", "java", "go", "rust", "c++", "ruby"],
}

_SPACY_LABEL_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "ORG": "ORG",
    "GPE": "GPE",
    "DATE": "DATE",
    "EMAIL": "EMAIL",
    "URL": "URL",
    "PRODUCT": "PRODUCT",
    "TECHNOLOGY": "TECHNOLOGY",
    "FILE_PATH": "FILE_PATH",
    "VERSION": "VERSION",
}

_DEP_RELATION_MAP: dict[str, str] = {
    "nsubj": "depends_on",
    "dobj": "acts_on",
    "nmod": "related_to",
    "conj": "related_to",
    "appos": "also_known_as",
    "xcomp": "complements",
    "ccomp": "contains",
}


def _lazy_spacy() -> Any:
    if not _SPACY_AVAILABLE:
        return None
    model = getattr(_lazy_spacy, "_model", None)
    if model is None:
        try:
            model = spacy.load("en_core_web_sm")
            _lazy_spacy._model = model  # type: ignore[attr-defined]
        except OSError:
            logger.warning("spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
            return None
    return model


class KnowledgeGraph:
    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._relations: list[Relation] = []
        self._graph: dict[str, set[str]] = {}
        self._reverse_graph: dict[str, set[str]] = {}

    def add_entity(self, name: str, ent_type: str, metadata: dict[str, Any] | None = None) -> Entity:
        existing = self._find_entity(name)
        if existing:
            return existing
        entity = Entity(
            id=uuid.uuid4().hex[:12],
            name=name,
            type=ent_type,
            metadata=metadata or {},
        )
        self._entities[entity.id] = entity
        self._graph[entity.id] = set()
        self._reverse_graph[entity.id] = set()
        return entity

    def _find_entity(self, name: str) -> Entity | None:
        for entity in self._entities.values():
            if entity.name.lower() == name.lower():
                return entity
        return None

    def add_relation(self, source_id: str, target_id: str, rel_type: str, metadata: dict[str, Any] | None = None) -> Relation:
        if source_id not in self._entities or target_id not in self._entities:
            raise ValueError("Both source and target must exist")
        relation = Relation(
            id=uuid.uuid4().hex[:12],
            source_id=source_id, target_id=target_id,
            rel_type=rel_type, metadata=metadata or {},
        )
        self._relations.append(relation)
        self._graph.setdefault(source_id, set()).add(target_id)
        self._reverse_graph.setdefault(target_id, set()).add(source_id)
        return relation

    def extract_from_document(self, document: Document) -> dict[str, list[str]]:
        entities_added: list[str] = []
        relations_added: list[str] = []

        spacy_nlp = _lazy_spacy()
        if spacy_nlp is not None and len(document.text) < 100000:
            self._extract_with_spacy(spacy_nlp, document, entities_added, relations_added)

        self._extract_with_regex(document, entities_added, relations_added)
        self._extract_tech_keywords(document, entities_added)

        return {"entities": entities_added, "relations": relations_added}

    def _extract_with_spacy(self, nlp: Any, document: Document, entities_added: list[str], relations_added: list[str]) -> None:
        doc: Doc = nlp(document.text)

        for ent in doc.ents:
            mapped_type = _SPACY_LABEL_MAP.get(ent.label_, "PRODUCT")
            entity = self.add_entity(ent.text, mapped_type, {"source": document.source, "type": mapped_type})
            if entity.name not in entities_added:
                entities_added.append(entity.name)

        for sent in doc.sents:
            for token in sent.root.subtree:
                if token.dep_ in _DEP_RELATION_MAP and token.head != token:
                    subj_ent = self._find_entity_by_span(self._get_entity_span(token.head, doc))
                    obj_ent = self._find_entity_by_span(self._get_entity_span(token, doc))
                    if subj_ent and obj_ent and subj_ent.id != obj_ent.id:
                        rel_type = _DEP_RELATION_MAP[token.dep_]
                        try:
                            self.add_relation(subj_ent.id, obj_ent.id, rel_type, {"source": document.source})
                            relations_added.append(f"{subj_ent.name} --{rel_type}--> {obj_ent.name}")
                        except ValueError:
                            logger.debug("Duplicate relation skipped: {} --{}--> {}", subj_ent.name, rel_type, obj_ent.name)

    def _get_entity_span(self, token: Any, doc: Doc) -> str:
        for ent in doc.ents:
            if ent.start <= token.i < ent.end:
                return ent.text  # type: ignore[no-any-return]
        return token.text  # type: ignore[no-any-return]

    def _find_entity_by_span(self, span_text: str) -> Entity | None:
        for entity in self._entities.values():
            if entity.name.lower() == span_text.lower():
                return entity
        return None

    def _extract_with_regex(self, document: Document, entities_added: list[str], relations_added: list[str]) -> None:
        for ent_type, patterns in _ENTITY_PATTERNS:
            for pattern in patterns:
                for match in pattern.finditer(document.text):
                    name = match.group(1) if match.lastindex else match.group(0)
                    entity = self.add_entity(name.strip(), ent_type, {"source": document.source, "type": ent_type})
                    if entity.name not in entities_added:
                        entities_added.append(entity.name)

        for rel_type, pattern in _RELATION_PATTERNS:
            for match in pattern.finditer(document.text):
                if match.lastindex and match.lastindex >= 2:
                    source = self._find_entity(match.group(1))
                    target = self._find_entity(match.group(2))
                    if source and target and source.id != target.id:
                        try:
                            self.add_relation(source.id, target.id, rel_type)
                            relations_added.append(f"{source.name} --{rel_type}--> {target.name}")
                        except ValueError:
                            logger.debug("Duplicate relation skipped: {} --{}--> {}", source.name, rel_type, target.name)

    def _extract_tech_keywords(self, document: Document, entities_added: list[str]) -> None:
        text_lower = document.text.lower()
        for kw_type, keywords in _TECH_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    self.add_entity(kw, kw_type, {"source": document.source, "type": kw_type})
                    if kw not in entities_added:
                        entities_added.append(kw)

    def search(self, query: str, max_depth: int = 2) -> list[dict[str, Any]]:
        query_lower = query.lower()
        seed_entities = [
            e for e in self._entities.values()
            if query_lower in e.name.lower() or query_lower in e.type.lower()
        ]
        if not seed_entities:
            return []

        results: list[dict[str, Any]] = []
        visited: set[str] = set()
        for seed in seed_entities:
            self._bfs(seed.id, max_depth, visited, results)

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        return unique

    def _bfs(self, start_id: str, max_depth: int, visited: set[str], results: list[dict[str, Any]]) -> None:
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        while queue:
            current_id, depth = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)

            entity = self._entities.get(current_id)
            if not entity:
                continue

            neighbors = self._get_neighbors(current_id)
            results.append({
                "id": entity.id, "name": entity.name,
                "type": entity.type, "metadata": entity.metadata,
                "neighbors": neighbors[:10],
            })

            if depth < max_depth:
                for nid in self._graph.get(current_id, set()) | self._reverse_graph.get(current_id, set()):
                    if nid not in visited:
                        queue.append((nid, depth + 1))

    def _get_neighbors(self, entity_id: str) -> list[dict[str, str]]:
        neighbors: list[dict[str, str]] = []
        for rel in self._relations:
            if rel.source_id == entity_id:
                target = self._entities.get(rel.target_id)
                if target:
                    neighbors.append({"entity": target.name, "type": target.type, "relation": rel.rel_type})
            elif rel.target_id == entity_id:
                source = self._entities.get(rel.source_id)
                if source:
                    neighbors.append({"entity": source.name, "type": source.type, "relation": f"inverse_{rel.rel_type}"})
        return neighbors

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def get_relations(self, entity_id: str) -> list[Relation]:
        return [
            rel for rel in self._relations
            if rel.source_id == entity_id or rel.target_id == entity_id
        ]

    def get_stats(self) -> dict[str, Any]:
        type_counts: dict[str, int] = {}
        rel_type_counts: dict[str, int] = {}
        for entity in self._entities.values():
            type_counts[entity.type] = type_counts.get(entity.type, 0) + 1
        for rel in self._relations:
            rel_type_counts[rel.rel_type] = rel_type_counts.get(rel.rel_type, 0) + 1
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "entity_types": type_counts,
            "relation_types": rel_type_counts,
        }

    def export_vis(self) -> dict[str, Any]:
        nodes = [
            {"id": e.id, "name": e.name, "type": e.type, "metadata": e.metadata}
            for e in self._entities.values()
        ]
        links = [
            {
                "source": r.source_id,
                "target": r.target_id,
                "relation": r.rel_type,
                "id": r.id,
            }
            for r in self._relations
        ]
        return {"nodes": nodes, "links": links}

    def save(self, path: str | Path) -> None:
        data = {
            "entities": {eid: {"id": e.id, "name": e.name, "type": e.type, "metadata": e.metadata}
                         for eid, e in self._entities.items()},
            "relations": [
                {"id": r.id, "source_id": r.source_id, "target_id": r.target_id,
                 "rel_type": r.rel_type, "metadata": r.metadata}
                for r in self._relations
            ],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._entities = {eid: Entity(**ed) for eid, ed in data.get("entities", {}).items()}
        self._relations = [Relation(**rd) for rd in data.get("relations", [])]
        self._graph = {eid: set() for eid in self._entities}
        self._reverse_graph = {eid: set() for eid in self._entities}
        for rel in self._relations:
            self._graph.setdefault(rel.source_id, set()).add(rel.target_id)
            self._reverse_graph.setdefault(rel.target_id, set()).add(rel.source_id)
