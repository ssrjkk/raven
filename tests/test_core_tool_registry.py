from __future__ import annotations

from raven.core.tool_registry import ToolRegistry


class TestToolRegistry:
    def setup_method(self) -> None:
        self.registry = ToolRegistry()

    async def _dummy_handler(self, **kwargs: object) -> str:
        return "ok"

    def test_register(self):
        self.registry.register("coding", "test_tool", self._dummy_handler)
        assert self.registry.get("coding", "test_tool") is not None

    def test_unregister(self):
        self.registry.register("coding", "test_tool", self._dummy_handler)
        self.registry.unregister("coding", "test_tool")
        assert self.registry.get("coding", "test_tool") is None

    def test_get_nonexistent(self):
        assert self.registry.get("coding", "nonexistent") is None

    def test_get_category(self):
        self.registry.register("coding", "t1", self._dummy_handler)
        self.registry.register("coding", "t2", self._dummy_handler)
        cat = self.registry.get_category("coding")
        assert len(cat) == 2

    def test_list_tools(self):
        self.registry.register("coding", "t1", self._dummy_handler)
        self.registry.register("automation", "t2", self._dummy_handler)
        tools = self.registry.list_tools()
        assert len(tools) == 2

    def test_search(self):
        self.registry.register("coding", "format_code", self._dummy_handler)
        self.registry.register("automation", "deploy", self._dummy_handler)
        results = self.registry.search("code")
        assert len(results) == 1
        assert results[0]["name"] == "format_code"

    def test_total_count(self):
        assert self.registry.total_count == 0
        self.registry.register("coding", "t1", self._dummy_handler)
        assert self.registry.total_count == 1

    def test_categories(self):
        self.registry.register("coding", "t1", self._dummy_handler)
        self.registry.register("automation", "t2", self._dummy_handler)
        assert set(self.registry.categories) == {"coding", "automation", "system"}

    def test_dynamic_category(self):
        self.registry.register("custom", "t1", self._dummy_handler)
        assert self.registry.get("custom", "t1") is not None
