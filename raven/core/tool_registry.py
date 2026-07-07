from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Callable[..., Awaitable[Any]]]] = {
            "coding": {},
            "automation": {},
            "system": {},
        }

    def register(
        self,
        category: str,
        name: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        if category not in self._tools:
            self._tools[category] = {}
        self._tools[category][name] = handler

    def unregister(self, category: str, name: str) -> None:
        if category in self._tools and name in self._tools[category]:
            del self._tools[category][name]

    def get(self, category: str, name: str) -> Callable[..., Awaitable[Any]] | None:
        return self._tools.get(category, {}).get(name)

    def get_category(self, category: str) -> dict[str, Callable[..., Awaitable[Any]]]:
        return dict(self._tools.get(category, {}))

    def list_tools(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for category, tools in self._tools.items():
            for name in tools:
                result.append({"category": category, "name": name})
        return result

    def search(self, query: str) -> list[dict[str, str]]:
        q = query.lower()
        result: list[dict[str, str]] = []
        for category, tools in self._tools.items():
            for name in tools:
                if q in name.lower() or q in category.lower():
                    result.append({"category": category, "name": name})
        return result

    @property
    def total_count(self) -> int:
        return sum(len(tools) for tools in self._tools.values())

    @property
    def categories(self) -> list[str]:
        return list(self._tools.keys())
