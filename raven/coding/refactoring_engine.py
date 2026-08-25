from __future__ import annotations

import ast
import asyncio
import difflib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

try:
    from tree_sitter import Language, Parser
    from tree_sitter_python import language as python_language

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False

_KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "int",
        "float",
        "str",
        "bool",
        "bytes",
        "bytearray",
        "None",
        "Any",
        "object",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
        "type",
        "Optional",
        "Union",
        "Literal",
        "TypeVar",
        "Generic",
        "Protocol",
        "TypedDict",
        "Callable",
        "Iterable",
        "Iterator",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Awaitable",
        "AsyncIterable",
        "AsyncIterator",
        "Path",
        "PathLike",
        "Self",
        "Final",
        "ClassVar",
        "Never",
        "NoReturn",
        "overload",
    }
)


class BreakingChangeError(Exception):
    def __init__(self, message: str, changes: list[str] | None = None) -> None:
        self.changes = changes or []
        super().__init__(message)


@dataclass(slots=True)
class FileChange:
    path: str
    old_content: str
    new_content: str
    change_type: str = "edit"


@dataclass(slots=True)
class RefactoringPlan:
    description: str
    changes: list[FileChange] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    safe_to_apply: bool = False


@dataclass(slots=True)
class DependencyEdge:
    source: str
    target: str
    dep_type: str = "import"


class DependencyGraph:
    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._edges: list[DependencyEdge] = []

    def add_node(self, path: str) -> None:
        self._nodes.add(path)

    def add_edge(self, edge: DependencyEdge) -> None:
        self._edges.append(edge)
        self._nodes.add(edge.source)
        self._nodes.add(edge.target)

    def get_dependents(self, path: str) -> list[str]:
        return [e.source for e in self._edges if e.target == path]

    def get_dependencies(self, path: str) -> list[str]:
        return [e.target for e in self._edges if e.source == path]

    def topological_sort(self, paths: list[str] | None = None) -> list[str]:
        nodes = paths or list(self._nodes)
        visited: set[str] = set()
        result: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in self.get_dependencies(node):
                if dep in nodes:
                    visit(dep)
            if node in nodes:
                result.append(node)

        for node in nodes:
            visit(node)
        return result


@dataclass(slots=True)
class ParamInfo:
    name: str
    has_default: bool


@dataclass(slots=True)
class FunctionInfo:
    name: str
    params: list[ParamInfo]
    has_return_type: bool
    start_line: int
    end_line: int


@dataclass(slots=True)
class ClassInfo:
    name: str
    methods: list[FunctionInfo]
    start_line: int
    end_line: int


class TreeSitterParser:
    def __init__(self) -> None:
        self._available = _TREE_SITTER_AVAILABLE
        if self._available:
            try:
                self._parser = Parser()
                self._parser.set_language(Language(python_language()))
                logger.debug("Tree-sitter parser initialized with Python language")
            except Exception as exc:
                logger.warning("Tree-sitter initialization failed: {}", exc)
                self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def parse(self, source: str) -> object:
        if self._available:
            return self._parser.parse(source.encode("utf-8"))
        return ast.parse(source)

    def extract_functions(self, source: str) -> list[FunctionInfo]:
        if self._available:
            return self._extract_functions_ts(source)
        return self._extract_functions_ast(source)

    def extract_classes(self, source: str) -> list[ClassInfo]:
        if self._available:
            return self._extract_classes_ts(source)
        return self._extract_classes_ast(source)

    def extract_imports(self, source: str) -> list[str]:
        if self._available:
            return self._extract_imports_ts(source)
        return self._extract_imports_ast(source)

    # --- tree-sitter implementations ---

    def _extract_functions_ts(self, source: str) -> list[FunctionInfo]:
        tree = self._parser.parse(source.encode("utf-8"))
        functions: list[FunctionInfo] = []
        self._ts_walk_functions(tree.root_node, source, functions)
        return functions

    def _ts_walk_functions(self, node: object, source: str, functions: list[FunctionInfo]) -> None:
        n = node
        if hasattr(n, "type") and n.type == "function_definition":
            name_node = n.child_by_field_name("name")  # type: ignore[attr-defined]
            params_node = n.child_by_field_name("parameters")  # type: ignore[attr-defined]
            return_type_node = n.child_by_field_name("return_type")  # type: ignore[attr-defined]
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte]
                params: list[ParamInfo] = []
                if params_node:
                    params = self._ts_extract_params(params_node, source)
                functions.append(
                    FunctionInfo(
                        name=name,
                        params=params,
                        has_return_type=return_type_node is not None,
                        start_line=n.start_point[0] + 1,  # type: ignore[attr-defined]
                        end_line=n.end_point[0] + 1,  # type: ignore[attr-defined]
                    )
                )
        if hasattr(n, "children"):
            for child in n.children:
                self._ts_walk_functions(child, source, functions)

    def _ts_extract_params(self, params_node: object, source: str) -> list[ParamInfo]:
        params: list[ParamInfo] = []
        if not hasattr(params_node, "children"):
            return params
        for child in params_node.children:
            ct = child.type
            if ct == "identifier":
                params.append(ParamInfo(name=source[child.start_byte : child.end_byte], has_default=False))
            elif ct == "typed_parameter":
                name_child = child.child_by_field_name("name")
                if name_child:
                    params.append(
                        ParamInfo(name=source[name_child.start_byte : name_child.end_byte], has_default=False)
                    )
            elif ct in ("default_parameter", "typed_default_parameter"):
                name_child = child.child_by_field_name("name")
                if name_child:
                    params.append(ParamInfo(name=source[name_child.start_byte : name_child.end_byte], has_default=True))
            elif ct == "list_splat_pattern":
                name_child = child.child_by_field_name("name")
                if name_child:
                    params.append(
                        ParamInfo(name=f"*{source[name_child.start_byte : name_child.end_byte]}", has_default=False)
                    )
            elif ct == "dictionary_splat_pattern":
                name_child = child.child_by_field_name("name")
                if name_child:
                    params.append(
                        ParamInfo(name=f"**{source[name_child.start_byte : name_child.end_byte]}", has_default=False)
                    )
        return params

    def _extract_classes_ts(self, source: str) -> list[ClassInfo]:
        tree = self._parser.parse(source.encode("utf-8"))
        classes: list[ClassInfo] = []
        self._ts_walk_classes(tree.root_node, source, classes)
        return classes

    def _ts_walk_classes(self, node: object, source: str, classes: list[ClassInfo]) -> None:
        n = node
        if hasattr(n, "type") and n.type == "class_definition":
            name_node = n.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte]
                methods: list[FunctionInfo] = []
                body = n.child_by_field_name("body")  # type: ignore[attr-defined]
                if body and hasattr(body, "children"):
                    for child in body.children:
                        if hasattr(child, "type") and child.type == "function_definition":
                            m_name_node = child.child_by_field_name("name")
                            m_params_node = child.child_by_field_name("parameters")
                            m_return_type = child.child_by_field_name("return_type")
                            if m_name_node:
                                m_name = source[m_name_node.start_byte : m_name_node.end_byte]
                                m_params: list[ParamInfo] = []
                                if m_params_node:
                                    m_params = self._ts_extract_params(m_params_node, source)
                                methods.append(
                                    FunctionInfo(
                                        name=m_name,
                                        params=m_params,
                                        has_return_type=m_return_type is not None,
                                        start_line=child.start_point[0] + 1,
                                        end_line=child.end_point[0] + 1,
                                    )
                                )
                classes.append(
                    ClassInfo(
                        name=name,
                        methods=methods,
                        start_line=n.start_point[0] + 1,  # type: ignore[attr-defined]
                        end_line=n.end_point[0] + 1,  # type: ignore[attr-defined]
                    )
                )
        if hasattr(n, "children"):
            for child in n.children:
                self._ts_walk_classes(child, source, classes)

    def _extract_imports_ts(self, source: str) -> list[str]:
        tree = self._parser.parse(source.encode("utf-8"))
        imports: list[str] = []
        self._ts_walk_imports(tree.root_node, source, imports)
        return imports

    def _ts_walk_imports(self, node: object, source: str, imports: list[str]) -> None:
        n = node
        if not hasattr(n, "type"):
            return
        if n.type == "import_statement":
            for child in n.children:  # type: ignore[attr-defined]
                if hasattr(child, "type") and child.type == "dotted_name":
                    imports.append(source[child.start_byte : child.end_byte].replace(".", "/") + ".py")
        elif n.type == "import_from_statement":
            module_node = n.child_by_field_name("module_name")  # type: ignore[attr-defined]
            if module_node:
                imports.append(source[module_node.start_byte : module_node.end_byte].replace(".", "/") + ".py")
        if hasattr(n, "children"):
            for child in n.children:
                self._ts_walk_imports(child, source, imports)

    # --- stdlib ast fallback implementations ---

    def _extract_functions_ast(self, source: str) -> list[FunctionInfo]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        functions: list[FunctionInfo] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = self._ast_extract_params(node)
                functions.append(
                    FunctionInfo(
                        name=node.name,
                        params=params,
                        has_return_type=node.returns is not None,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    )
                )
        return functions

    @staticmethod
    def _ast_extract_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ParamInfo]:
        params: list[ParamInfo] = []
        total_args = len(func_node.args.args)
        total_defaults = len(func_node.args.defaults)
        for i, arg in enumerate(func_node.args.args):
            has_default = i >= total_args - total_defaults
            params.append(ParamInfo(name=arg.arg, has_default=has_default))
        return params

    def _extract_classes_ast(self, source: str) -> list[ClassInfo]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        classes: list[ClassInfo] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods: list[FunctionInfo] = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        params = self._ast_extract_params(item)
                        methods.append(
                            FunctionInfo(
                                name=item.name,
                                params=params,
                                has_return_type=item.returns is not None,
                                start_line=item.lineno,
                                end_line=item.end_lineno or item.lineno,
                            )
                        )
                classes.append(
                    ClassInfo(
                        name=node.name,
                        methods=methods,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    )
                )
        return classes

    def _extract_imports_ast(self, source: str) -> list[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.replace(".", "/") + ".py")
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.replace(".", "/") + ".py")
        return imports


class RefactoringEngine:
    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._dep_graph = DependencyGraph()

    async def build_dependency_graph(self, paths: list[str] | None = None) -> DependencyGraph:
        self._dep_graph = await asyncio.to_thread(self._build_graph_sync, paths)
        return self._dep_graph

    def _build_graph_sync(self, paths: list[str] | None) -> DependencyGraph:
        g = DependencyGraph()
        search_paths = [self._workspace / p for p in paths] if paths else [self._workspace]
        for search_path in search_paths:
            if not search_path.is_dir() and search_path.is_file():
                deps = self._extract_imports(str(search_path))
                g.add_node(str(search_path))
                for dep in deps:
                    g.add_edge(DependencyEdge(source=str(search_path), target=dep))
            elif search_path.is_dir():
                for py_file in search_path.rglob("*.py"):
                    deps = self._extract_imports(str(py_file))
                    g.add_node(str(py_file))
                    for dep in deps:
                        g.add_edge(DependencyEdge(source=str(py_file), target=dep))
        return g

    def _extract_imports(self, file_path: str) -> list[str]:
        try:
            source = Path(file_path).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return []
        parser = TreeSitterParser()
        return parser.extract_imports(source)

    async def plan_refactoring(self, file_path: str, description: str) -> RefactoringPlan:
        full_path = self._workspace / file_path
        if not full_path.exists():
            return RefactoringPlan(description=description, changes=[], risks=["File not found"], safe_to_apply=False)
        await self.build_dependency_graph()
        deps = self._dep_graph.get_dependents(file_path)
        risks: list[str] = []
        if deps:
            risks.append(f"Affects {len(deps)} dependent files: {', '.join(deps[:5])}")
        return RefactoringPlan(
            description=description,
            changes=[],
            risks=risks,
            safe_to_apply=len(risks) == 0,
        )

    def apply_changes(self, changes: list[FileChange], backup: bool = True) -> list[str]:
        results: list[str] = []
        for change in changes:
            full_path = self._workspace / change.path
            if backup and full_path.exists():
                backup_path = full_path.with_suffix(full_path.suffix + ".bak")
                try:
                    shutil.copy2(str(full_path), str(backup_path))
                except Exception as exc:
                    logger.warning("Backup failed for {}: {}", change.path, exc)
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(change.new_content, encoding="utf-8")
                results.append(f"Applied {change.change_type} to {change.path}")
            except Exception as exc:
                results.append(f"Failed to apply {change.change_type} to {change.path}: {exc}")
        return results

    def rollback(self, paths: list[str]) -> list[str]:
        results: list[str] = []
        for path_str in paths:
            path = Path(path_str)
            backup = path.with_suffix(path.suffix + ".bak")
            if backup.exists():
                try:
                    shutil.copy2(str(backup), str(path))
                    backup.unlink()
                    results.append(f"Rolled back {path_str}")
                except Exception as exc:
                    results.append(f"Rollback failed for {path_str}: {exc}")
            else:
                results.append(f"No backup found for {path_str}")
        return results

    def compute_diff(self, old_content: str, new_content: str, path: str) -> str:
        return "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=path,
                tofile=path,
            )
        )

    def detect_breaking_changes(self, old_content: str, new_content: str) -> list[str]:
        parser = TreeSitterParser()
        old_funcs = parser.extract_functions(old_content)
        new_funcs = parser.extract_functions(new_content)

        old_map: dict[str, FunctionInfo] = {f.name: f for f in old_funcs}
        new_map: dict[str, FunctionInfo] = {f.name: f for f in new_funcs}

        changes: list[str] = []

        for name in old_map:
            if name not in new_map and not name.startswith("_"):
                changes.append(f"Removed public function '{name}'")

        for name, func in old_map.items():
            if name in new_map:
                new_func = new_map[name]
                old_param_map = {p.name: p for p in func.params}
                new_param_map = {p.name: p for p in new_func.params}

                for pname in old_param_map:
                    if pname not in new_param_map:
                        changes.append(f"Removed parameter '{pname}' from '{name}'")

                for pname, np_info in new_param_map.items():
                    if pname not in old_param_map and not np_info.has_default:
                        changes.append(f"Added required parameter '{pname}' to '{name}'")

                for pname in old_param_map:
                    if pname in new_param_map:
                        old_has_default = old_param_map[pname].has_default
                        new_has_default = new_param_map[pname].has_default
                        if old_has_default and not new_has_default:
                            changes.append(f"Parameter '{pname}' in '{name}' changed from optional to required")

                if func.has_return_type and not new_func.has_return_type:
                    changes.append(f"Removed return type annotation from '{name}'")

        old_classes = parser.extract_classes(old_content)
        new_classes = parser.extract_classes(new_content)
        old_class_map: dict[str, ClassInfo] = {c.name: c for c in old_classes}
        new_class_map: dict[str, ClassInfo] = {c.name: c for c in new_classes}

        for name in old_class_map:
            if name not in new_class_map:
                changes.append(f"Removed class '{name}'")

        return changes

    async def type_check(self, file_path: str) -> list[str]:
        full_path = self._workspace / file_path
        if not full_path.exists():
            return [f"File not found: {file_path}"]

        issues: list[str] = []

        if shutil.which("mypy"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "mypy",
                    "--ignore-missing-imports",
                    str(full_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                output = stdout.decode() + stderr.decode()
                if proc.returncode != 0:
                    issues = self._parse_type_checker_output(output)
                    if issues:
                        return issues
            except Exception as exc:
                logger.debug("mypy invocation failed: {}", exc)

        if shutil.which("pyright"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pyright",
                    str(full_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                output = stdout.decode() + stderr.decode()
                if proc.returncode != 0:
                    issues = self._parse_type_checker_output(output)
                    if issues:
                        return issues
            except Exception as exc:
                logger.debug("pyright invocation failed: {}", exc)

        ast_issues = self._ast_type_check_fallback(full_path)
        issues.extend(ast_issues)
        return issues

    @staticmethod
    def _parse_type_checker_output(output: str) -> list[str]:
        return [line.strip() for line in output.splitlines() if "error:" in line]

    @staticmethod
    def _ast_type_check_fallback(file_path: Path) -> list[str]:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [f"Syntax error in {file_path.name}: {exc}"]
        except FileNotFoundError:
            return [f"File not found: {file_path.name}"]

        defined: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    defined.add(alias.asname or alias.name)

        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    if isinstance(arg.annotation, ast.Name):
                        name = arg.annotation.id
                        if name[0].isupper() and name not in _KNOWN_TYPES and name not in defined:
                            issues.append(
                                f"Unknown type '{name}' for arg '{arg.arg}' in '{node.name}' at line {node.lineno}"
                            )
                if isinstance(node.returns, ast.Name):
                    name = node.returns.id
                    if name[0].isupper() and name not in _KNOWN_TYPES and name not in defined:
                        issues.append(f"Unknown return type '{name}' in '{node.name}' at line {node.lineno}")
            elif isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name):
                name = node.annotation.id
                if name[0].isupper() and name not in _KNOWN_TYPES and name not in defined:
                    issues.append(f"Unknown type '{name}' in annotation at line {node.lineno}")
        return issues

    async def refactor(
        self,
        changes: list[FileChange],
        *,
        description: str = "",
        check_breaking: bool = True,
        backup: bool = True,
    ) -> RefactoringPlan:
        if not changes:
            return RefactoringPlan(description=description or "No changes", safe_to_apply=True)

        parser = TreeSitterParser()

        for change in changes:
            if change.new_content.strip():
                try:
                    parser.parse(change.new_content)
                except (SyntaxError, Exception) as exc:
                    msg = f"Parse failed for {change.path}: {exc}"
                    logger.error(msg)
                    return RefactoringPlan(description=description, changes=[], risks=[msg], safe_to_apply=False)

        if check_breaking:
            all_breaking: list[str] = []
            for change in changes:
                if change.old_content:
                    breaking = self.detect_breaking_changes(change.old_content, change.new_content)
                    all_breaking.extend(f"{change.path}: {b}" for b in breaking)
            if all_breaking:
                raise BreakingChangeError("Breaking changes detected", changes=all_breaking)

        await self.build_dependency_graph()

        apply_results = await asyncio.to_thread(self.apply_changes, changes, backup)
        failed_applies = [r for r in apply_results if r.startswith("Failed")]
        if failed_applies:
            for r in failed_applies:
                logger.error(r)
            return RefactoringPlan(description=description, changes=[], risks=failed_applies, safe_to_apply=False)

        type_issues: list[str] = []
        for change in changes:
            issues = await self.type_check(change.path)
            type_issues.extend(issues)

        if type_issues:
            logger.warning("Type checking failed after refactoring, rolling back")
            rollback_results = await asyncio.to_thread(
                self.rollback, [str(self._workspace / c.path) for c in changes]
            )
            for r in rollback_results:
                logger.info(r)
            msg_0 = f"Type checking failed: {'; '.join(type_issues[:3])}"
            raise BreakingChangeError(
                msg_0,
                changes=type_issues,
            )

        logger.info("Refactoring applied successfully: {}", description)
        return RefactoringPlan(
            description=description or "Refactoring applied successfully",
            changes=changes,
            safe_to_apply=True,
        )
