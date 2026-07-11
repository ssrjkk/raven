from __future__ import annotations

import pytest

from raven.coding.test_generator import ClassInfo, FunctionInfo, TestGenerator, TypeInfo


class TestFunctionInfo:
    def test_create_function(self):
        f = FunctionInfo(name="add", args=[TypeInfo(name="x", type_hint="int"), TypeInfo(name="y", type_hint="int")],
                         return_type="int", docstring="Add two numbers")
        assert f.name == "add"
        assert len(f.args) == 2
        assert f.return_type == "int"


class TestClassInfo:
    def test_create_class(self):
        c = ClassInfo(name="Calculator", methods=[], docstring="A simple calculator")
        assert c.name == "Calculator"
        assert c.methods == []


class TestTestGenerator:
    @pytest.mark.asyncio
    async def test_extract_types(self, tmp_path):
        src = tmp_path / "example.py"
        src.write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"

class Adder:
    def add(self, x: int, y: int) -> int:
        return x + y
""")
        gen = TestGenerator(str(tmp_path))
        types = await gen.extract_types("example.py")
        assert len(types) >= 2
        funcs = [t for t in types if hasattr(t, 'args') and not isinstance(t, ClassInfo)]
        classes = [t for t in types if isinstance(t, ClassInfo)]
        assert any(f.name == "greet" for f in funcs)
        assert any(c.name == "Adder" for c in classes)

    @pytest.mark.asyncio
    async def test_generate_tests(self, tmp_path):
        src = tmp_path / "calc.py"
        src.write_text("""
def add(x: int, y: int) -> int:
    return x + y
""")
        gen = TestGenerator(str(tmp_path))
        tests = await gen.generate_tests("calc.py")
        assert "def test_add_basic" in tests
        assert "calc" in tests

    def test_generate_test_for_function(self):
        gen = TestGenerator()
        func = FunctionInfo(name="add", args=[TypeInfo(name="x", type_hint="int"), TypeInfo(name="y", type_hint="int")],
                            return_type="int")
        test = gen.generate_test_for_function(func, "calc.py")
        assert "test_add_basic" in test
        assert "def test_add_edge_empty" in test

    def test_generate_test_value(self):
        gen = TestGenerator()
        assert gen._generate_test_value("str") == '"test"'
        assert gen._generate_test_value("int") == "0"
        assert gen._generate_test_value("bool") == "False"
        assert gen._generate_test_value("list") == "[]"

    @pytest.mark.asyncio
    async def test_save_tests(self, tmp_path):
        src = tmp_path / "math.py"
        src.write_text("def add(x: int, y: int) -> int: return x + y")
        gen = TestGenerator(str(tmp_path))
        result = await gen.save_tests("math.py", "test content")
        assert "saved" in result.lower()
        test_dir = tmp_path / "test"
        assert test_dir.exists()

    @pytest.mark.asyncio
    async def test_generate_tests_file_not_found(self, tmp_path):
        gen = TestGenerator(str(tmp_path))
        result = await gen.generate_tests("nonexistent.py")
        assert "not found" in result

    def test_get_type_hint(self):
        import ast
        gen = TestGenerator()
        arg = ast.arg(arg="x", annotation=ast.Name(id="int"))
        assert gen._get_type_hint(arg) == "int"
        arg_no_annotation = ast.arg(arg="y", annotation=None)
        assert gen._get_type_hint(arg_no_annotation) == "Any"
