from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent.parent / "services" / "code-service"
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

tools_mod = importlib.import_module("tools")
ToolRegistry = tools_mod.ToolRegistry
ReadFileTool = tools_mod.ReadFileTool
WriteFileTool = tools_mod.WriteFileTool
GlobTool = tools_mod.GlobTool


class TestToolRegistry:
    def test_list_content(self):
        r = ToolRegistry()
        tools = r.list()
        assert "read_file" in tools
        assert "write_file" in tools
        assert "glob" in tools

    def test_execute_unknown(self):
        r = ToolRegistry()
        result = r.execute("nonexistent")
        assert "unknown tool" in result


class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_execute_nonexistent(self):
        t = ReadFileTool()
        result = await t.execute(path="/nonexistent/file.txt")
        assert "file not found" in result


class TestWriteFileTool:
    @pytest.mark.asyncio
    async def test_execute_bad_path(self):
        t = WriteFileTool()
        result = await t.execute(path="", content="test")
        assert "error" in result.lower() or "denied" in result


class TestGlobTool:
    @pytest.mark.asyncio
    async def test_execute_empty_pattern(self):
        t = GlobTool()
        result = await t.execute(pattern="")
        assert isinstance(result, str)
