from __future__ import annotations

import pytest

from ravencode.runtime.tools import MODULE_TOOLS, _ensure_plugin_tools


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
