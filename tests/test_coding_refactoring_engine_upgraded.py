from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from raven.coding.refactoring_engine import (
    BreakingChangeError,
    FileChange,
    FunctionInfo,
    ParamInfo,
    RefactoringPlan,
    TreeSitterParser,
)


class TestTreeSitterParser:
    def test_init_available(self):
        parser = TreeSitterParser()
        assert parser.available is bool(hasattr(parser, "_parser"))

    @patch("raven.coding.refactoring_engine._TREE_SITTER_AVAILABLE", False)
    def test_init_unavailable(self):
        parser = TreeSitterParser()
        assert parser.available is False

    def test_extract_functions(self):
        source = """
def foo(a, b: int) -> str:
    return "hello"

def bar(x=1):
    pass

async def baz():
    await asyncio.sleep(1)
"""
        parser = TreeSitterParser()
        funcs = parser.extract_functions(source)
        names = {f.name for f in funcs}
        assert names == {"foo", "bar", "baz"}
        foo = next(f for f in funcs if f.name == "foo")
        assert any(p.name == "a" and p.has_default is False for p in foo.params)
        assert any(p.name == "b" and p.has_default is False for p in foo.params)
        assert foo.has_return_type is True
        bar = next(f for f in funcs if f.name == "bar")
        assert any(p.name == "x" and p.has_default is True for p in bar.params)

    def test_extract_classes(self):
        source = """
class Animal:
    def speak(self) -> str:
        return "?"

class Dog(Animal):
    def bark(self, volume: int = 10):
        pass
"""
        parser = TreeSitterParser()
        classes = parser.extract_classes(source)
        names = {c.name for c in classes}
        assert names == {"Animal", "Dog"}
        dog = next(c for c in classes if c.name == "Dog")
        assert any(m.name == "bark" for m in dog.methods)
        bark = next(m for m in dog.methods if m.name == "bark")
        assert any(p.name == "volume" and p.has_default is True for p in bark.params)

    def test_extract_imports(self):
        source = "import os\nfrom pathlib import Path\nimport typing as t\n"
        parser = TreeSitterParser()
        imports = parser.extract_imports(source)
        assert any("os" in i for i in imports)
        assert any("pathlib" in i for i in imports)
        assert any("typing" in i for i in imports)

    @patch("raven.coding.refactoring_engine._TREE_SITTER_AVAILABLE", False)
    def test_fallback_to_stdlib_ast(self):
        source = """
import sys
def compute(x: int) -> str:
    return str(x)
"""
        parser = TreeSitterParser()
        assert parser.available is False
        funcs = parser.extract_functions(source)
        assert len(funcs) == 1
        assert funcs[0].name == "compute"
        assert any(p.name == "x" for p in funcs[0].params)
        assert funcs[0].has_return_type is True

        imports = parser.extract_imports(source)
        assert any("sys" in i for i in imports)


class TestDetectBreakingChanges:
    @pytest.fixture
    def engine(self):
        from raven.coding.refactoring_engine import RefactoringEngine
        return RefactoringEngine()

    async def test_removed_public_function(self, engine):
        old = "def foo(): pass\ndef bar(): pass\n"
        new = "def bar(): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert any("foo" in c for c in changes)

    async def test_removed_private_function_not_reported(self, engine):
        old = "def _internal(): pass\ndef bar(): pass\n"
        new = "def bar(): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert not any("_internal" in c for c in changes)

    async def test_removed_param(self, engine):
        old = "def foo(x, y): pass\n"
        new = "def foo(x): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert any("y" in c and "Removed" in c for c in changes)

    async def test_added_required_param(self, engine):
        old = "def foo(x): pass\n"
        new = "def foo(x, y): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert any("y" in c and "required" in c for c in changes)

    async def test_added_optional_param_not_breaking(self, engine):
        old = "def foo(x): pass\n"
        new = "def foo(x, y=None): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert not any("y" in c for c in changes)

    async def test_param_changed_to_required(self, engine):
        old = "def foo(x=1): pass\n"
        new = "def foo(x): pass\n"
        changes = engine.detect_breaking_changes(old, new)
        assert any("required" in c for c in changes)

    async def test_no_changes_for_identical(self, engine):
        source = "def foo(x): pass\n"
        changes = engine.detect_breaking_changes(source, source)
        assert changes == []


class TestTypeCheck:
    @pytest.fixture
    def engine(self, tmp_path):
        from raven.coding.refactoring_engine import RefactoringEngine
        return RefactoringEngine(str(tmp_path))

    async def test_type_check_pass(self, engine, tmp_path):
        (tmp_path / "valid.py").write_text("x: int = 1\n")
        issues = await engine.type_check("valid.py")
        assert isinstance(issues, list)

    async def test_type_check_syntax_error(self, engine, tmp_path):
        (tmp_path / "bad_syntax.py").write_text("def foo(:\n")
        issues = await engine.type_check("bad_syntax.py")
        assert len(issues) > 0

    async def test_type_check_file_not_found(self, engine):
        issues = await engine.type_check("nonexistent.py")
        assert any("not found" in i for i in issues)


class TestRefactor:
    async def test_rollback_on_type_failure(self, tmp_path):
        from raven.coding.refactoring_engine import RefactoringEngine

        src = tmp_path / "target.py"
        original = "x: int = 1\n"
        src.write_text(original)

        engine = RefactoringEngine(str(tmp_path))
        change = FileChange(path="target.py", old_content=original, new_content="x = broken syntax\n")

        plan = await engine.refactor([change], description="bad refactor", check_breaking=False, backup=True)
        assert plan.safe_to_apply is False
        assert src.read_text() == original

    async def test_refactor_success(self, tmp_path):
        from raven.coding.refactoring_engine import RefactoringEngine

        src = tmp_path / "safe.py"
        original = "x: int = 1\ny: int = 2\n"
        src.write_text(original)

        engine = RefactoringEngine(str(tmp_path))
        new_content = "x: int = 10\ny: int = 20\n"
        change = FileChange(path="safe.py", old_content=original, new_content=new_content)

        plan = await engine.refactor([change], description="update values", check_breaking=False, backup=True)
        assert plan.safe_to_apply is True
        assert src.read_text() == new_content

    async def test_breaking_change_raises_error(self, tmp_path):
        from raven.coding.refactoring_engine import RefactoringEngine

        engine = RefactoringEngine(str(tmp_path))
        old = "def greet(name: str) -> str: return f'Hi {name}'\n"
        new = "# function removed\n"

        with pytest.raises(BreakingChangeError) as excinfo:
            await engine.refactor(
                [FileChange(path="removed.py", old_content=old, new_content=new)],
                description="remove function",
                check_breaking=True,
            )
        assert excinfo.value.changes


class TestDependencyGraph:
    async def test_build_dependency_graph(self, tmp_path):
        from raven.coding.refactoring_engine import RefactoringEngine

        a = tmp_path / "a.py"
        a.write_text("import b")
        b = tmp_path / "b.py"
        b.write_text("x = 1")
        engine = RefactoringEngine(str(tmp_path))
        g = await engine.build_dependency_graph()
        deps = g.get_dependencies(str(a))
        assert any("b.py" in d for d in deps)
