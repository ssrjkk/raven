from __future__ import annotations

import pytest

from raven.coding.refactoring_engine import DependencyEdge, DependencyGraph, FileChange, RefactoringEngine


class TestDependencyGraph:
    def test_add_node(self):
        g = DependencyGraph()
        g.add_node("a.py")
        assert "a.py" in g._nodes

    def test_add_edge(self):
        g = DependencyGraph()
        g.add_edge(DependencyEdge(source="a.py", target="b.py"))
        assert g.get_dependents("b.py") == ["a.py"]
        assert g.get_dependencies("a.py") == ["b.py"]

    def test_topological_sort(self):
        g = DependencyGraph()
        g.add_edge(DependencyEdge(source="c.py", target="b.py"))
        g.add_edge(DependencyEdge(source="b.py", target="a.py"))
        result = g.topological_sort(["a.py", "b.py", "c.py"])
        assert result.index("a.py") < result.index("b.py")
        assert result.index("b.py") < result.index("c.py")

    def test_topological_sort_partial(self):
        g = DependencyGraph()
        g.add_edge(DependencyEdge(source="b.py", target="a.py"))
        g.add_edge(DependencyEdge(source="c.py", target="a.py"))
        result = g.topological_sort(["c.py", "a.py"])
        assert result.index("a.py") < result.index("c.py")

    def test_empty_graph(self):
        g = DependencyGraph()
        assert g.topological_sort() == []


class TestFileChange:
    def test_create_change(self):
        c = FileChange(path="src/main.py", old_content="old", new_content="new", change_type="edit")
        assert c.path == "src/main.py"
        assert c.change_type == "edit"

    def test_default_change_type(self):
        c = FileChange(path="f.py", old_content="", new_content="x")
        assert c.change_type == "edit"


class TestRefactoringEngine:
    @pytest.mark.asyncio
    async def test_plan_refactoring_nonexistent(self, tmp_path):
        engine = RefactoringEngine(str(tmp_path))
        plan = await engine.plan_refactoring("nonexistent.py", "fix bug")
        assert plan.safe_to_apply is False

    @pytest.mark.asyncio
    async def test_extract_imports(self, tmp_path):
        src = tmp_path / "mod.py"
        src.write_text("import os\nfrom pathlib import Path\n")
        engine = RefactoringEngine(str(tmp_path))
        imports = await engine._extract_imports(str(src))
        assert any("os" in i for i in imports)
        assert any("pathlib" in i for i in imports)

    @pytest.mark.asyncio
    async def test_apply_changes(self, tmp_path):
        engine = RefactoringEngine(str(tmp_path))
        changes = [FileChange(path="test.txt", old_content="", new_content="hello", change_type="create")]
        results = await engine.apply_changes(changes, backup=False)
        assert any("Applied" in r for r in results)
        assert (tmp_path / "test.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_apply_changes_backup(self, tmp_path):
        src = tmp_path / "target.txt"
        src.write_text("original")
        engine = RefactoringEngine(str(tmp_path))
        changes = [FileChange(path="target.txt", old_content="original", new_content="modified", change_type="edit")]
        results = await engine.apply_changes(changes, backup=True)
        assert any("Applied" in r for r in results)
        assert src.read_text() == "modified"
        assert (tmp_path / "target.txt.bak").exists()

    @pytest.mark.asyncio
    async def test_rollback(self, tmp_path):
        src = tmp_path / "roll.txt"
        src.write_text("original")
        engine = RefactoringEngine(str(tmp_path))
        await engine.apply_changes([FileChange(path="roll.txt", old_content="original", new_content="modified")], backup=True)
        results = await engine.rollback([str(src)])
        assert any("Rolled back" in r for r in results)
        assert src.read_text() == "original"

    @pytest.mark.asyncio
    async def test_compute_diff(self):
        engine = RefactoringEngine()
        diff = await engine.compute_diff("hello\n", "hello world\n", "f.txt")
        assert "hello" in diff

    @pytest.mark.asyncio
    async def test_build_dependency_graph(self, tmp_path):
        a = tmp_path / "a.py"
        a.write_text("import b")
        b = tmp_path / "b.py"
        b.write_text("x = 1")
        engine = RefactoringEngine(str(tmp_path))
        g = await engine.build_dependency_graph()
        deps = g.get_dependencies(str(a))
        assert any("b.py" in d for d in deps)
