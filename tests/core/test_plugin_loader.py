from __future__ import annotations


import pytest

from raven.core.plugin_loader import PluginLoader, func_to_tool


class TestFuncToTool:
    def test_simple_function(self):
        async def my_tool(name: str, age: int = 25) -> str:
            """My test tool. Args: name (str): The name"""
            return f"{name} is {age}"

        tool = func_to_tool(my_tool)
        assert tool.name == "my_tool"
        assert tool.description == "My test tool."
        assert "name" in tool.parameters["properties"]
        assert "age" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["name"]

    def test_no_params(self):
        async def ping() -> str:
            """Simple ping"""
            return "pong"

        tool = func_to_tool(ping)
        assert tool.name == "ping"
        assert tool.parameters["properties"] == {}

    def test_various_types(self):
        async def multi(a: str, b: int, c: float, d: bool) -> str:
            """Multi type test"""
            return ""

        tool = func_to_tool(multi)
        props = tool.parameters["properties"]
        assert props["a"]["type"] == "string"
        assert props["b"]["type"] == "integer"
        assert props["c"]["type"] == "number"
        assert props["d"]["type"] == "boolean"


class TestPluginLoader:
    @pytest.fixture
    def loader(self):
        return PluginLoader()

    def test_empty_dir(self, loader, tmp_path):
        tools = loader.load_from_dir(tmp_path)
        assert tools == []

    def test_load_plugin_file(self, loader, tmp_path):
        plugin_dir = tmp_path / "testplugin"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "plugin.py"
        plugin_file.write_text("""
PLUGIN_NAME = "testplugin"
PLUGIN_DESCRIPTION = "A test plugin"

async def hello(name: str) -> str:
    \"\"\"Say hello. Args: name (str): Name to greet\"\"\"
    return f"Hello {name}"

async def add(a: int, b: int) -> int:
    \"\"\"Add two numbers\"\"\"
    return a + b
""")
        tools = loader.load_from_dir(plugin_dir)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"hello", "add"}

    def test_existing_tools(self, loader, tmp_path):
        plugin_dir = tmp_path / "p1"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("""
async def foo() -> str:
    \"\"\"Foo function\"\"\"
    return "foo"
""")
        loader.load_from_dir(plugin_dir)
        assert len(loader.tools) == 1
        assert loader.get_tool("foo") is not None

        plugin_dir2 = tmp_path / "p2"
        plugin_dir2.mkdir()
        (plugin_dir2 / "plugin.py").write_text("""
async def bar() -> str:
    \"\"\"Bar function\"\"\"
    return "bar"
""")
        loader.load_from_dir(plugin_dir2)
        assert len(loader.tools) == 2

    def test_to_openai_tools(self, loader, tmp_path):
        plugin_dir = tmp_path / "p1"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("""
async def test_tool(x: str) -> str:
    \"\"\"Test. Args: x (str): The X\"\"\"
    return x
""")
        loader.load_from_dir(plugin_dir)
        openai = loader.to_openai_tools()
        assert len(openai) == 1
        assert openai[0]["type"] == "function"
        assert openai[0]["function"]["name"] == "test_tool"

    def test_clear(self, loader, tmp_path):
        plugin_dir = tmp_path / "p1"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("async def f() -> str:\n    return ''\n")
        loader.load_from_dir(plugin_dir)
        assert len(loader.tools) == 1
        loader.clear()
        assert len(loader.tools) == 0
