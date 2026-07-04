from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from raven.core.workflow.models import WorkflowTemplate

if TYPE_CHECKING:
    from raven.core.db import Database


class WorkflowStore:
    def __init__(self, db: Database | None = None):
        self._db = db
        self._templates: dict[str, WorkflowTemplate] = {}
        self._lock = threading.Lock()

    def bind_db(self, db: Database) -> None:
        self._db = db

    def register(self, template: WorkflowTemplate) -> None:
        with self._lock:
            self._templates[template.id] = template

    def register_many(self, templates: list[WorkflowTemplate]) -> None:
        with self._lock:
            for t in templates:
                self._templates[t.id] = t

    def get(self, template_id: str) -> WorkflowTemplate | None:
        with self._lock:
            return self._templates.get(template_id)

    def list_templates(self, category: str | None = None) -> list[WorkflowTemplate]:
        with self._lock:
            if category:
                return [t for t in self._templates.values() if t.category.value == category]
            return list(self._templates.values())

    def list_categories(self) -> list[str]:
        with self._lock:
            cats: set[str] = set()
            for t in self._templates.values():
                cats.add(t.category.value)
            return sorted(cats)

    def count(self) -> int:
        with self._lock:
            return len(self._templates)

    def search(self, query: str) -> list[WorkflowTemplate]:
        q = query.lower()
        with self._lock:
            return [
                t
                for t in self._templates.values()
                if q in t.name.lower() or q in t.description.lower() or q in t.id.lower()
            ]
