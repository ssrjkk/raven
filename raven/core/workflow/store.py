from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.workflow.models import WorkflowTemplate

if TYPE_CHECKING:
    from raven.core.db import Database


class WorkflowStore:
    def __init__(self, db: Database | None = None):
        self._db = db
        self._templates: dict[str, WorkflowTemplate] = {}

    def bind_db(self, db: Database) -> None:
        self._db = db

    def register(self, template: WorkflowTemplate) -> None:
        self._templates[template.id] = template

    def register_many(self, templates: list[WorkflowTemplate]) -> None:
        for t in templates:
            self.register(t)

    def get(self, template_id: str) -> WorkflowTemplate | None:
        return self._templates.get(template_id)

    def list_templates(self, category: str | None = None) -> list[WorkflowTemplate]:
        if category:
            return [t for t in self._templates.values() if t.category.value == category]
        return list(self._templates.values())

    def list_categories(self) -> list[str]:
        cats: set[str] = set()
        for t in self._templates.values():
            cats.add(t.category.value)
        return sorted(cats)

    def count(self) -> int:
        return len(self._templates)

    def search(self, query: str) -> list[WorkflowTemplate]:
        q = query.lower()
        return [
            t
            for t in self._templates.values()
            if q in t.name.lower() or q in t.description.lower() or q in t.id.lower()
        ]
