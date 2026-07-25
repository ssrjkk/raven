from __future__ import annotations

import ast
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from raven.core.llm import LLMProvider

    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    LLMProvider = None  # type: ignore[assignment,misc]


class LLMInterface(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str: ...


class LLMProviderAdapter(LLMInterface):
    def __init__(self, provider: Any, model: str = "default") -> None:
        self._provider = provider
        self._model = model

    async def generate(self, prompt: str) -> str:
        if not hasattr(self._provider, "complete"):
            return ""
        resp = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
        )
        return resp.content  # type: ignore[no-any-return]


@dataclass
class TestResult:
    passed: bool = True
    coverage: float = 0.0
    test_count: int = 0
    edge_cases: list[str] = field(default_factory=list)


@dataclass
class TypeInfo:
    name: str
    type_hint: str
    default_value: str | None = None
    docstring: str = ""


@dataclass
class FunctionInfo:
    name: str
    args: list[TypeInfo] = field(default_factory=list)
    return_type: str = ""
    docstring: str = ""
    is_async: bool = False
    is_method: bool = False


@dataclass
class ClassInfo:
    name: str
    methods: list[FunctionInfo] = field(default_factory=list)
    docstring: str = ""


_BUILTIN_TYPES = {"list", "dict", "tuple", "set", "str", "int", "float", "bool", "None", "Any"}

_TEST_VALUE_MAP: dict[str, str] = {
    "str": '"test"',
    "int": "0",
    "float": "0.0",
    "bool": "False",
    "list": "[]",
    "dict": "{}",
    "tuple": "()",
    "set": "set()",
    "None": "None",
    "Any": "None",
}

_EDGE_CASE_SUGGESTIONS: dict[str, list[str]] = {
    "str": [
        "Test with empty string for '{name}'",
        "Test with very long string for '{name}'",
        "Test with whitespace-only string for '{name}'",
    ],
    "int": [
        "Test with zero for '{name}'",
        "Test with negative value for '{name}'",
        "Test with very large value for '{name}'",
    ],
    "float": [
        "Test with zero for '{name}'",
        "Test with negative value for '{name}'",
        "Test with NaN or infinity for '{name}'",
    ],
    "bool": [
        "Test with both True and False for '{name}'",
    ],
    "list": [
        "Test with empty list for '{name}'",
        "Test with very large list for '{name}'",
    ],
    "dict": [
        "Test with empty dict for '{name}'",
    ],
    "tuple": [
        "Test with empty tuple for '{name}'",
    ],
    "set": [
        "Test with empty set for '{name}'",
    ],
}


class TestGenerator:
    def __init__(
        self,
        workspace: str | None = None,
        llm_provider: LLMInterface | None = None,
        llm_model: str = "default",
    ) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._llm_provider = llm_provider
        self._llm_model = llm_model

    async def _generate_with_llm(self, prompt: str) -> str:
        if self._llm_provider is None:
            return ""
        try:
            result = await self._llm_provider.generate(prompt)
            return result.strip()
        except Exception as exc:
            logger.warning("LLM test generation failed: {}", exc)
            return ""

    def extract_types(self, file_path: str) -> list[FunctionInfo | ClassInfo]:
        full_path = self._resolve_path(file_path)
        try:
            tree = ast.parse(full_path.read_text(encoding="utf-8"))
        except (SyntaxError, FileNotFoundError):
            return []

        results: list[FunctionInfo | ClassInfo] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                results.append(self._extract_function(node))
            elif isinstance(node, ast.ClassDef):
                results.append(self._extract_class(node))
        return results

    def _get_type_hint(self, arg: ast.arg) -> str:
        if arg.annotation is None:
            return "Any"
        if isinstance(arg.annotation, ast.Name):
            return arg.annotation.id
        if isinstance(arg.annotation, ast.Constant) and isinstance(arg.annotation.value, str):
            return arg.annotation.value
        if isinstance(arg.annotation, ast.Subscript):
            return self._subscript_to_str(arg.annotation)
        if isinstance(arg.annotation, ast.Attribute):
            return f"{self._attribute_to_str(arg.annotation)}"
        return ""

    def _subscript_to_str(self, node: ast.Subscript) -> str:
        value = ""
        if isinstance(node.value, ast.Name):
            value = node.value.id
        elif isinstance(node.value, ast.Attribute):
            value = self._attribute_to_str(node.value)
        if isinstance(node.slice, ast.Name):
            return f"{value}[{node.slice.id}]"
        if isinstance(node.slice, ast.Constant):
            return f"{value}[{node.slice.value}]"  # type: ignore[str-bytes-safe]
        if isinstance(node.slice, ast.Tuple):
            elts = [
                self._subscript_to_str(e)
                if isinstance(e, ast.Subscript)
                else (e.id if isinstance(e, ast.Name) else str(getattr(e, "value", "")))
                for e in node.slice.elts
            ]
            return f"{value}[{', '.join(elts)}]"
        return value

    def _attribute_to_str(self, node: ast.Attribute) -> str:
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def _get_return_type(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        if node.returns is None:
            return ""
        if isinstance(node.returns, ast.Name):
            return node.returns.id
        if isinstance(node.returns, ast.Constant) and isinstance(node.returns.value, str):
            return node.returns.value
        if isinstance(node.returns, ast.Subscript):
            return self._subscript_to_str(node.returns)
        if isinstance(node.returns, ast.Attribute):
            return self._attribute_to_str(node.returns)
        return ""

    def _extract_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
        return FunctionInfo(
            name=node.name,
            args=[TypeInfo(name=a.arg, type_hint=self._get_type_hint(a)) for a in node.args.args],
            return_type=self._get_return_type(node),
            docstring=ast.get_docstring(node) or "",
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=isinstance(getattr(node, "parent", None), ast.ClassDef),
        )

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        methods: list[FunctionInfo] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                item.parent = node  # type: ignore[union-attr]
                methods.append(
                    FunctionInfo(
                        name=item.name,
                        args=[TypeInfo(name=a.arg, type_hint=self._get_type_hint(a)) for a in item.args.args],
                        return_type=self._get_return_type(item),
                        docstring=ast.get_docstring(item) or "",
                        is_async=isinstance(item, ast.AsyncFunctionDef),
                        is_method=True,
                    )
                )
        return ClassInfo(name=node.name, methods=methods, docstring=ast.get_docstring(node) or "")

    def generate_test_for_function(self, func: FunctionInfo, module_path: str) -> str:
        module_name = Path(module_path).stem
        lines: list[str] = [
            "from __future__ import annotations",
            "",
            "import pytest",
            f"from {module_name} import {func.name}",
            "",
        ]
        lines.extend(self._get_type_imports(func))
        lines.append("")
        lines.append(f"class Test{func.name.capitalize()}:")

        args_str = ", ".join(
            a.default_value if a.default_value is not None else self._generate_test_value(a.type_hint)
            for a in func.args
        )
        lines.append(f"    def test_{func.name}_basic(self):")
        lines.append(f"        result = {func.name}({args_str})" if args_str else f"        result = {func.name}()")
        lines.append("        assert result is not None")
        lines.append(f"        assert isinstance(result, {func.return_type or 'object'})")
        lines.append("")
        lines.append(f"    def test_{func.name}_edge_empty(self):")
        lines.append("        with pytest.raises((TypeError, ValueError)):")
        lines.append(f"            {func.name}()")
        lines.append("            pytest.fail('Should have raised')")
        return "\n".join(lines)

    def _get_type_imports(self, func: FunctionInfo) -> list[str]:
        imports: list[str] = []
        seen: set[str] = set()
        for arg in func.args:
            hint = arg.type_hint
            if hint in _BUILTIN_TYPES:
                continue
            if hint and hint not in seen and hint[0].isupper():
                imports.append(f"from {hint.lower()} import {hint}")
                seen.add(hint)
        return imports

    def _generate_test_value(self, type_hint: str) -> str:
        for key, val in _TEST_VALUE_MAP.items():
            if key in type_hint:
                return val
        return "None"

    async def generate_tests(self, file_path: str) -> str:
        full_path = self._resolve_path(file_path)
        if not full_path.exists():
            return f"# File not found: {file_path}"

        types = self.extract_types(file_path)
        output: list[str] = [f"# Auto-generated tests for {file_path}", ""]

        for t in types:
            if isinstance(t, FunctionInfo):
                output.append(self.generate_test_for_function(t, file_path))
                output.append("")
            elif isinstance(t, ClassInfo):
                output.extend(self._generate_class_tests(t, file_path))

        return "\n".join(output)

    def _generate_class_tests(self, cls: ClassInfo, file_path: str) -> list[str]:
        module_name = Path(file_path).stem
        lines: list[str] = [
            f"from {module_name} import {cls.name}",
            "",
            f"class Test{cls.name}:",
        ]
        for method in cls.methods:
            if method.name.startswith("_"):
                continue
            args = [self._generate_test_value(a.type_hint) for a in method.args if a.name != "self"]
            args_str = ", ".join(args) if args else ""
            lines.append(f"    def test_{method.name}_basic(self):")
            lines.append(f"        instance = {cls.name}()")
            if args_str:
                lines.append(f"        result = instance.{method.name}({args_str})")
            else:
                lines.append(f"        result = instance.{method.name}()")
            lines.append("        assert result is not None")
            lines.append("")
        return lines

    async def save_tests(self, source_path: str, test_content: str | None = None) -> str:
        if test_content is None:
            test_content = await self.generate_tests(source_path)
        src = self._resolve_path(source_path)
        test_dir = src.parent / "test"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / f"test_{src.stem}.py"
        test_file.write_text(test_content, encoding="utf-8")
        return f"Tests saved to {test_file}"

    def _resolve_path(self, path: str) -> Path:
        return Path(path) if Path(path).is_absolute() else self._workspace / path

    async def detect_edge_cases(self, func: FunctionInfo) -> list[str]:
        edge_cases: list[str] = []

        if self._llm_provider is not None:
            prompt = (
                f"Analyze the following Python function signature and return a list of edge case "
                f"test descriptions (one per line, no numbering):\n\n"
                f"Function: {func.name}\n"
                f"Arguments: {', '.join(f'{a.name}: {a.type_hint}' for a in func.args)}\n"
                f"Return type: {func.return_type}\n"
                f"Async: {func.is_async}\n"
                f"Docstring: {func.docstring}\n"
            )
            llm_result = await self._generate_with_llm(prompt)
            if llm_result:
                for line in llm_result.split("\n"):
                    line = line.strip().strip("-").strip()
                    if line and not line.startswith("#"):
                        edge_cases.append(line)
                return edge_cases

        for arg in func.args:
            hint = arg.type_hint
            base_hint = hint.split("[")[0].split(" | ")[0] if hint else ""
            suggestions = _EDGE_CASE_SUGGESTIONS.get(base_hint, [])
            for suggestion in suggestions:
                edge_cases.append(suggestion.format(name=arg.name))
            if arg.default_value is None and base_hint not in ("", "Any"):
                edge_cases.append(f"Test with None for '{arg.name}' (no default)")
            if "None" in hint:
                edge_cases.append(f"Test with None value for '{arg.name}'")

        if func.is_async:
            edge_cases.append("Verify async behavior with cancelled task")

        seen: set[str] = set()
        result: list[str] = []
        for ec in edge_cases:
            if ec not in seen:
                seen.add(ec)
                result.append(ec)
        return result

    def optimize_for_coverage(self, source_path: str, test_path: str) -> TestResult:
        src = self._resolve_path(source_path)
        test_file = self._resolve_path(test_path)

        if not test_file.exists():
            logger.warning("Test file not found: {}", test_file)
            return TestResult(passed=False, coverage=0.0, test_count=0)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test_file),
                    f"--cov={src.parent}",
                    "--cov-report=xml",
                    "--cov-branch",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Coverage run timed out for {}", test_file)
            return TestResult(passed=False, coverage=0.0, test_count=0)
        except FileNotFoundError:
            logger.warning("pytest not found — cannot run coverage")
            return TestResult(passed=False, coverage=0.0, test_count=0)

        passed = result.returncode == 0
        coverage = 0.0

        cov_xml = Path.cwd() / "coverage.xml"
        if cov_xml.exists():
            coverage = self._parse_coverage_xml(cov_xml)
            cov_xml.unlink(missing_ok=True)
        cov_db = Path.cwd() / ".coverage"
        if cov_db.exists():
            cov_db.unlink(missing_ok=True)

        test_count = 0
        combined_output = (result.stdout or "") + (result.stderr or "")
        match = re.search(r"(\d+)\s+passed", combined_output)
        if match:
            test_count = int(match.group(1))

        return TestResult(passed=passed, coverage=coverage, test_count=test_count)

    @staticmethod
    def _parse_coverage_xml(xml_path: Path) -> float:
        try:
            from defusedxml.ElementTree import parse as safe_parse

            tree = safe_parse(xml_path)
            root = tree.getroot()
            line_rate = root.get("line-rate")
            if line_rate is not None:
                return float(line_rate) * 100.0
        except Exception:
            logger.warning("Failed to parse coverage XML: {}", xml_path)
        return 0.0
