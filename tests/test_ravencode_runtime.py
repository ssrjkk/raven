from __future__ import annotations

import pytest

from ravencode.runtime.tools import MODULE_TOOLS, _ensure_plugin_tools, execute_tool


class TestModuleTools:
    def test_has_read_tool(self):
        assert "read" in MODULE_TOOLS
        assert MODULE_TOOLS["read"]["dangerous"] is False

    def test_has_write_tool(self):
        assert "write" in MODULE_TOOLS
        assert MODULE_TOOLS["write"]["dangerous"] is True

    def test_has_edit_tool(self):
        assert "edit" in MODULE_TOOLS

    def test_has_bash_tool(self):
        assert "bash" in MODULE_TOOLS

    def test_has_glob_tool(self):
        assert "glob" in MODULE_TOOLS

    def test_has_grep_tool(self):
        assert "grep" in MODULE_TOOLS

    def test_has_canvas_tool(self):
        assert "canvas_render" in MODULE_TOOLS

    def test_has_nodes_tool(self):
        assert "nodes_list" in MODULE_TOOLS

    def test_has_cron_tools(self):
        assert "cron_schedule" in MODULE_TOOLS
        assert "cron_list" in MODULE_TOOLS
        assert "cron_cancel" in MODULE_TOOLS

    def test_has_sandbox_policy_tool(self):
        assert "sandbox_policy" in MODULE_TOOLS

    def test_has_talk_tool(self):
        assert "talk" in MODULE_TOOLS
        assert MODULE_TOOLS["talk"]["dangerous"] is False

    def test_each_tool_has_handler(self):
        for name, tool in MODULE_TOOLS.items():
            assert "handler" in tool, f"Tool {name} missing handler"
            assert callable(tool["handler"]), f"Tool {name} handler not callable"

    def test_each_tool_has_parameters(self):
        for name, tool in MODULE_TOOLS.items():
            assert "parameters" in tool, f"Tool {name} missing parameters"

    def test_plugin_tools_load(self):
        _ensure_plugin_tools()
        assert len(MODULE_TOOLS) >= 17

    def test_no_tools_with_same_name(self):
        names = [t["name"] for t in MODULE_TOOLS.values()]
        assert len(names) == len(set(names))


class TestExecuteToolValidation:
    @pytest.mark.asyncio
    async def test_rejects_missing_required_argument(self, monkeypatch):
        async def boom(**kwargs):
            raise AssertionError("handler must not be invoked on invalid arguments")

        monkeypatch.setitem(MODULE_TOOLS["write"], "handler", boom)
        result = await execute_tool("write", {"content": "x"})
        assert result.startswith("[error]")
        assert "path" in result

    @pytest.mark.asyncio
    async def test_rejects_unknown_property(self, monkeypatch):
        async def boom(**kwargs):
            raise AssertionError("handler must not be invoked on invalid arguments")

        monkeypatch.setitem(MODULE_TOOLS["write"], "handler", boom)
        result = await execute_tool("write", {"path": "a.txt", "content": "x", "surprise": 1})
        assert result.startswith("[error]")
        assert "surprise" in result

    @pytest.mark.asyncio
    async def test_rejects_wrong_type(self, monkeypatch):
        async def boom(**kwargs):
            raise AssertionError("handler must not be invoked on invalid arguments")

        monkeypatch.setitem(MODULE_TOOLS["write"], "handler", boom)
        result = await execute_tool("write", {"path": "a.txt", "content": 42})
        assert result.startswith("[error]")
        assert "content" in result

    @pytest.mark.asyncio
    async def test_valid_arguments_pass_through(self, monkeypatch):
        async def fake(path: str, content: str) -> str:
            return f"wrote {path}"

        monkeypatch.setitem(MODULE_TOOLS["write"], "handler", fake)
        result = await execute_tool("write", {"path": "a.txt", "content": "hello"})
        assert result == "wrote a.txt"

    @pytest.mark.asyncio
    async def test_unknown_tool_still_rejected(self):
        result = await execute_tool("definitely_not_a_tool", {})
        assert result.startswith("[error]")
        assert "unknown tool" in result
