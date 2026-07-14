from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.coding.test_generator import (
    ClassInfo,
    FunctionInfo,
    LLMInterface,
    LLMProviderAdapter,
    TestGenerator,
    TestResult,
    TypeInfo,
)


class TestTestResult:
    def test_defaults(self):
        r = TestResult()
        assert r.passed is True
        assert r.coverage == 0.0
        assert r.test_count == 0
        assert r.edge_cases == []

    def test_custom_values(self):
        r = TestResult(passed=False, coverage=85.5, test_count=12, edge_cases=["empty list", "None value"])
        assert r.passed is False
        assert r.coverage == 85.5
        assert r.test_count == 12
        assert r.edge_cases == ["empty list", "None value"]


class TestLLMProviderAdapter:
    @pytest.mark.asyncio
    async def test_generate_calls_complete(self):
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock()
        mock_provider.complete.return_value.content = "def test_hello(): pass"

        adapter = LLMProviderAdapter(mock_provider, model="test-model")
        result = await adapter.generate("generate a test")

        mock_provider.complete.assert_awaited_once()
        _args, kwargs = mock_provider.complete.call_args
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["messages"][0]["content"] == "generate a test"
        assert kwargs["model"] == "test-model"
        assert result == "def test_hello(): pass"

    @pytest.mark.asyncio
    async def test_generate_empty_when_no_complete(self):
        adapter = LLMProviderAdapter(object())
        result = await adapter.generate("prompt")
        assert result == ""


class TestLLMInterface:
    def test_abstract_method(self):
        with pytest.raises(TypeError):
            LLMInterface()  # type: ignore[abstract]


class TestDetectEdgeCases:
    @pytest.mark.asyncio
    async def test_detect_str_edge_cases(self):
        gen = TestGenerator()
        func = FunctionInfo(name="greet", args=[TypeInfo(name="name", type_hint="str")])
        cases = await gen.detect_edge_cases(func)
        assert any("empty string" in c for c in cases)
        assert any("very long string" in c for c in cases)
        assert any("whitespace" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_int_edge_cases(self):
        gen = TestGenerator()
        func = FunctionInfo(name="add", args=[TypeInfo(name="x", type_hint="int")])
        cases = await gen.detect_edge_cases(func)
        assert any("zero" in c for c in cases)
        assert any("negative" in c for c in cases)
        assert any("large value" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_bool_edge_cases(self):
        gen = TestGenerator()
        func = FunctionInfo(name="toggle", args=[TypeInfo(name="flag", type_hint="bool")])
        cases = await gen.detect_edge_cases(func)
        assert any("True and False" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_list_edge_cases(self):
        gen = TestGenerator()
        func = FunctionInfo(name="process", args=[TypeInfo(name="items", type_hint="list")])
        cases = await gen.detect_edge_cases(func)
        assert any("empty list" in c for c in cases)
        assert any("very large list" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_none_default_edge_case(self):
        gen = TestGenerator()
        func = FunctionInfo(name="fetch", args=[TypeInfo(name="url", type_hint="str", default_value=None)])
        cases = await gen.detect_edge_cases(func)
        assert any("None" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_union_none_edge_case(self):
        gen = TestGenerator()
        func = FunctionInfo(name="find", args=[TypeInfo(name="key", type_hint="str | None")])
        cases = await gen.detect_edge_cases(func)
        assert any("None" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_async_edge_case(self):
        gen = TestGenerator()
        func = FunctionInfo(name="poll", is_async=True)
        cases = await gen.detect_edge_cases(func)
        assert any("cancelled task" in c for c in cases)

    @pytest.mark.asyncio
    async def test_detect_edge_cases_deduplicates(self):
        gen = TestGenerator()
        func = FunctionInfo(
            name="multi",
            args=[
                TypeInfo(name="a", type_hint="str"),
                TypeInfo(name="b", type_hint="int"),
            ],
        )
        cases = await gen.detect_edge_cases(func)
        assert len(cases) == len(set(cases))


class TestDetectEdgeCasesWithLLM:
    @pytest.mark.asyncio
    async def test_llm_edge_case_generation(self):
        mock_llm = MagicMock(spec=LLMInterface)
        mock_llm.generate = AsyncMock(return_value="edge: empty string\nedge: None value\n")

        gen = TestGenerator(llm_provider=mock_llm)
        func = FunctionInfo(name="greet", args=[TypeInfo(name="name", type_hint="str")])
        cases = await gen.detect_edge_cases(func)

        mock_llm.generate.assert_awaited_once()
        assert any("empty string" in c or "edge: empty string" in c for c in cases)

    @pytest.mark.asyncio
    async def test_llm_fallback_on_exception(self):
        mock_llm = MagicMock(spec=LLMInterface)
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        gen = TestGenerator(llm_provider=mock_llm)
        func = FunctionInfo(name="greet", args=[TypeInfo(name="name", type_hint="str")])
        cases = await gen.detect_edge_cases(func)

        assert len(cases) > 0
        assert any("empty string" in c for c in cases)


class TestOptimizeForCoverage:
    @pytest.mark.asyncio
    async def test_optimize_coverage_success(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        src = tmp_path / "module.py"
        src.write_text("def foo(): return 42")
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def test_foo(): assert foo() == 42")

        cov_xml = tmp_path / "coverage.xml"
        cov_xml.write_text("""<?xml version="1.0"?>
<coverage line-rate="0.85" branch-rate="0.75">
</coverage>""")

        with (
            patch("raven.coding.test_generator.subprocess.run") as mock_run,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="4 passed in 0.1s", stderr="")
            result = await gen.optimize_for_coverage("module.py", str(test_file))

        assert result.passed is True
        assert result.coverage == 85.0
        assert result.test_count == 4

    @pytest.mark.asyncio
    async def test_optimize_coverage_failure(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        src = tmp_path / "module.py"
        src.write_text("def foo(): return 42")
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def test_foo(): assert False")

        with (
            patch("raven.coding.test_generator.subprocess.run") as mock_run,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="1 failed in 0.1s", stderr="")
            result = await gen.optimize_for_coverage("module.py", str(test_file))

        assert result.passed is False

    @pytest.mark.asyncio
    async def test_optimize_coverage_missing_test_file(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        result = await gen.optimize_for_coverage("module.py", "nonexistent.py")
        assert result.passed is False
        assert result.coverage == 0.0
        assert result.test_count == 0

    @pytest.mark.asyncio
    async def test_optimize_coverage_timeout(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def test_foo(): pass")

        with patch("raven.coding.test_generator.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=1)):
            result = await gen.optimize_for_coverage("module.py", str(test_file))

        assert result.passed is False
        assert result.coverage == 0.0

    @pytest.mark.asyncio
    async def test_optimize_coverage_pytest_not_found(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def test_foo(): pass")

        with patch("raven.coding.test_generator.subprocess.run", side_effect=FileNotFoundError):
            result = await gen.optimize_for_coverage("module.py", str(test_file))

        assert result.passed is False
        assert result.coverage == 0.0


class TestCoverageXmlParsing:
    def test_parse_valid_xml(self, tmp_path):
        xml = """<?xml version="1.0"?>
<coverage line-rate="0.85" branch-rate="0.75">
</coverage>"""
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(xml)

        result = TestGenerator._parse_coverage_xml(xml_path)
        assert result == 85.0

    def test_parse_zero_coverage(self, tmp_path):
        xml = """<?xml version="1.0"?>
<coverage line-rate="0.0">
</coverage>"""
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(xml)

        result = TestGenerator._parse_coverage_xml(xml_path)
        assert result == 0.0

    def test_parse_missing_file(self, tmp_path):
        result = TestGenerator._parse_coverage_xml(tmp_path / "nonexistent.xml")
        assert result == 0.0

    def test_parse_invalid_xml(self, tmp_path):
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text("not xml")

        result = TestGenerator._parse_coverage_xml(xml_path)
        assert result == 0.0


class TestBackwardCompat:
    @pytest.mark.asyncio
    async def test_extract_types_preserved(self, tmp_path):
        src = tmp_path / "example.py"
        src.write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""")
        gen = TestGenerator(str(tmp_path))
        types = await gen.extract_types("example.py")
        assert len(types) >= 1
        assert types[0].name == "greet"
        assert isinstance(types[0], FunctionInfo)
        assert types[0].args[0].type_hint == "str"

    def test_generate_test_for_function_preserved(self):
        gen = TestGenerator()
        func = FunctionInfo(name="add", args=[TypeInfo(name="x", type_hint="int"), TypeInfo(name="y", type_hint="int")], return_type="int")
        test = gen.generate_test_for_function(func, "calc.py")
        assert "test_add_basic" in test
        assert "test_add_edge_empty" in test
        assert "assert isinstance(result, int)" in test

    def test_generate_test_value_preserved(self):
        gen = TestGenerator()
        assert gen._generate_test_value("str") == '"test"'
        assert gen._generate_test_value("int") == "0"
        assert gen._generate_test_value("bool") == "False"
        assert gen._generate_test_value("list") == "[]"
        assert gen._generate_test_value("UnknownType") == "None"

    @pytest.mark.asyncio
    async def test_generate_tests_preserved(self, tmp_path):
        src = tmp_path / "calc.py"
        src.write_text("""
def add(x: int, y: int) -> int:
    return x + y
""")
        gen = TestGenerator(str(tmp_path))
        tests = await gen.generate_tests("calc.py")
        assert "def test_add_basic" in tests
        assert "calc" in tests

    @pytest.mark.asyncio
    async def test_save_tests_preserved(self, tmp_path):
        src = tmp_path / "math.py"
        src.write_text("def add(x: int, y: int) -> int: return x + y")
        gen = TestGenerator(str(tmp_path))
        result = await gen.save_tests("math.py", "test content")
        assert "saved" in result.lower()

    def test_get_type_hint_preserved(self):
        import ast
        gen = TestGenerator()
        arg = ast.arg(arg="x", annotation=ast.Name(id="int"))
        assert gen._get_type_hint(arg) == "int"
        arg_no_annotation = ast.arg(arg="y", annotation=None)
        assert gen._get_type_hint(arg_no_annotation) == "Any"


class TestLLMGeneration:
    @pytest.mark.asyncio
    async def test_generate_with_llm_success(self):
        mock_llm = MagicMock(spec=LLMInterface)
        mock_llm.generate = AsyncMock(return_value="def test_hello(): pass")

        gen = TestGenerator(llm_provider=mock_llm)
        result = await gen._generate_with_llm("write a test")
        assert result == "def test_hello(): pass"

    @pytest.mark.asyncio
    async def test_generate_with_llm_none_provider(self):
        gen = TestGenerator()
        result = await gen._generate_with_llm("write a test")
        assert result == ""

    @pytest.mark.asyncio
    async def test_generate_with_llm_exception(self):
        mock_llm = MagicMock(spec=LLMInterface)
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("fail"))

        gen = TestGenerator(llm_provider=mock_llm)
        result = await gen._generate_with_llm("write a test")
        assert result == ""


class TestConstructor:
    def test_default_workspace(self):
        gen = TestGenerator()
        assert gen._workspace == Path.cwd()

    def test_custom_workspace(self):
        gen = TestGenerator("C:\\temp")
        assert gen._workspace == Path("C:\\temp").resolve()

    def test_llm_provider_default_none(self):
        gen = TestGenerator()
        assert gen._llm_provider is None

    def test_llm_provider_custom(self):
        mock_llm = MagicMock(spec=LLMInterface)
        gen = TestGenerator(llm_provider=mock_llm)
        assert gen._llm_provider is mock_llm
