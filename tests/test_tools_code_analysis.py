from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.code_analysis import analyze_code, explain_code, register_code_analysis_tools


class TestCodeAnalysisTools:
    def _make_py_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "sample.py"
        f.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "def greet(name: str) -> str:\n"
            '    """Say hello."""\n'
            '    return f"Hello, {name}"\n'
            "\n"
            "class Calculator:\n"
            "    def add(self, a: int, b: int) -> int:\n"
            '        """Add two numbers."""\n'
            "        return a + b\n"
        )
        return f

    def test_analyze_code_summary(self, tmp_path: Path) -> None:
        f = self._make_py_file(tmp_path)
        result = analyze_code(str(f), detail="summary")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_analyze_code_symbols(self, tmp_path: Path) -> None:
        f = self._make_py_file(tmp_path)
        result = analyze_code(str(f), detail="symbols")
        assert "greet" in result
        assert "Calculator" in result

    def test_analyze_code_path_not_found(self) -> None:
        result = analyze_code("/nonexistent/path/file.py")
        assert "not found" in result

    def test_explain_code(self, tmp_path: Path) -> None:
        f = self._make_py_file(tmp_path)
        result = explain_code(str(f))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_explain_code_not_found(self) -> None:
        result = explain_code("/nonexistent/file.py")
        assert "not found" in result

    def test_analyze_code_directory(self, tmp_path: Path) -> None:
        self._make_py_file(tmp_path)
        result = analyze_code(str(tmp_path))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_code_analysis_tools(registry)
        assert registry.get("analyze_code") is not None
        assert registry.get("explain_code") is not None
