from __future__ import annotations

import ast
import builtins
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BUILTIN_NAMES = {name for name in dir(builtins) if not name.startswith("_")}
_STDLIB_MODULES: set[str] | None = None


def _stdlib_modules() -> set[str]:
    global _STDLIB_MODULES
    if _STDLIB_MODULES is None:
        _STDLIB_MODULES = set()
        for m in sys.stdlib_module_names:
            _STDLIB_MODULES.add(m)
    return _STDLIB_MODULES


@dataclass
class ResolvedImport:
    module: str
    name: str
    alias: str | None
    origin: str  # "stdlib" | "third-party" | "local"
    source_path: Path | None = None
    line: int = 0


@dataclass
class CalledFunction:
    name: str
    line: int
    column: int
    resolved_module: str | None = None
    resolved_file: Path | None = None
    resolved_line: int | None = None
    is_builtin: bool = False


@dataclass
class SymbolDef:
    name: str
    kind: str  # "function" | "class" | "method" | "variable" | "constant"
    line: int
    column: int
    end_line: int
    parent: str | None = None
    docstring: str = ""
    calls: list[CalledFunction] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)


@dataclass
class AnnotatedLine:
    number: int
    code: str
    explanation: str = ""
    origin_info: str = ""
    is_definition: bool = False
    is_call: bool = False
    is_import: bool = False
    call_target: str = ""


@dataclass
class AnalysisResult:
    file_path: Path
    language: str
    total_lines: int
    imports: list[ResolvedImport] = field(default_factory=list)
    symbols: list[SymbolDef] = field(default_factory=list)
    call_graph: list[tuple[str, str, int]] = field(default_factory=list)
    annotated_lines: list[AnnotatedLine] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    summary: str = ""


class _ImportTracker(ast.NodeVisitor):
    def __init__(self, root: Path, file_path: Path) -> None:
        self.root = root
        self.file_path = file_path
        self.imports: list[ResolvedImport] = []

    def _resolve_origin(self, module: str) -> tuple[str, Path | None]:
        top = module.split(".")[0] if module else ""
        if not top:
            return ("unknown", None)
        if top in _stdlib_modules():
            return ("stdlib", None)
        try:
            spec = __import__(top).__spec__
            if spec and spec.origin:
                origin_path = Path(spec.origin)
                try:
                    origin_path.relative_to(self.root)
                    return ("local", origin_path)
                except ValueError:
                    return ("third-party", None)
        except ImportError:
            pass
        candidate = self.root / top.replace(".", "/")
        if (self.file_path.parent / f"{top}.py").exists():
            return ("local", self.file_path.parent / f"{top}.py")
        if candidate.exists() or (self.root / top.replace(".", "/")).exists():
            return ("local", candidate if candidate.exists() else self.root / top.replace(".", "/"))
        if (self.root / f"{top}.py").exists():
            return ("local", self.root / f"{top}.py")
        return ("third-party", None)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            origin, src = self._resolve_origin(alias.name)
            self.imports.append(ResolvedImport(
                module=alias.name,
                name=alias.name,
                alias=alias.asname,
                origin=origin,
                source_path=src,
                line=node.lineno,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            origin, src = self._resolve_origin(module)
            self.imports.append(ResolvedImport(
                module=module,
                name=alias.name,
                alias=alias.asname,
                origin=origin,
                source_path=src,
                line=node.lineno,
            ))


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[CalledFunction] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.append(CalledFunction(
                name=node.func.id,
                line=node.lineno,
                column=node.col_offset,
                is_builtin=node.func.id in _BUILTIN_NAMES,
            ))
        elif isinstance(node.func, ast.Attribute):
            name = self._format_attr(node.func)
            self.calls.append(CalledFunction(
                name=name,
                line=node.lineno,
                column=node.col_offset,
            ))
        self.generic_visit(node)

    def _format_attr(self, node: ast.Attribute) -> str:
        parts: list[str] = [node.attr]
        current: ast.expr = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        elif isinstance(current, ast.Call):
            parts.append("<call>")
        else:
            parts.append("<expr>")
        return ".".join(reversed(parts))


class _DefCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[SymbolDef] = []
        self._current_class: str | None = None

    def _doc(self, node: ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef) -> str:
        return (ast.get_docstring(node) or "").strip()

    def _decorators(self, node: ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef) -> list[str]:
        result: list[str] = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                result.append(d.id)
            elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                result.append(f"{d.func.id}(...)")
            elif isinstance(d, ast.Attribute):
                result.append(self._format_attr(d))
        return result

    def _format_attr(self, node: ast.Attribute) -> str:
        parts: list[str] = [node.attr]
        current: ast.expr = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def _collect_calls_from(self, node: ast.AST) -> list[CalledFunction]:
        collector = _CallCollector()
        collector.visit(node)
        return collector.calls

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        sym = SymbolDef(
            name=node.name,
            kind="method" if self._current_class else "function",
            line=node.lineno,
            column=node.col_offset,
            end_line=node.end_lineno or node.lineno,
            parent=self._current_class,
            docstring=self._doc(node),
            decorators=self._decorators(node),
            calls=self._collect_calls_from(node),
        )
        self.symbols.append(sym)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        sym = SymbolDef(
            name=node.name,
            kind="method" if self._current_class else "function",
            line=node.lineno,
            column=node.col_offset,
            end_line=node.end_lineno or node.lineno,
            parent=self._current_class,
            docstring=self._doc(node),
            decorators=self._decorators(node),
            calls=self._collect_calls_from(node),
        )
        self.symbols.append(sym)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev = self._current_class
        self._current_class = node.name
        bases: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(self._format_attr(base))
        sym = SymbolDef(
            name=node.name,
            kind="class",
            line=node.lineno,
            column=node.col_offset,
            end_line=node.end_lineno or node.lineno,
            docstring=self._doc(node),
            decorators=self._decorators(node),
        )
        self.symbols.append(sym)
        self.generic_visit(node)
        self._current_class = prev

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id.isupper():
                    self.symbols.append(SymbolDef(
                        name=target.id,
                        kind="constant",
                        line=target.lineno,
                        column=target.col_offset,
                        end_line=node.end_lineno or target.lineno,
                    ))
                else:
                    self.symbols.append(SymbolDef(
                        name=target.id,
                        kind="variable",
                        line=target.lineno,
                        column=target.col_offset,
                        end_line=node.end_lineno or target.lineno,
                    ))


class CodeAnalyzer:
    def __init__(self, root_path: str | Path = ".") -> None:
        self.root = Path(root_path).resolve()

    def explain_file(self, file_path: str | Path) -> AnalysisResult:
        path = (self.root / file_path).resolve()
        if not path.exists():
            return AnalysisResult(file_path=path, language="", total_lines=0, summary="File not found")
        if path.suffix != ".py":
            return self._analyze_non_python(path)
        return self._analyze_python(path)

    def analyze(self, path: str | Path = ".") -> dict[str, AnalysisResult]:
        target = (self.root / path).resolve()
        results: dict[str, AnalysisResult] = {}
        if target.is_file():
            result = self.explain_file(target)
            results[str(target)] = result
        elif target.is_dir():
            for py_file in sorted(target.rglob("*.py")):
                if ".venv" in str(py_file) or "__pycache__" in str(py_file):
                    continue
                results[str(py_file)] = self._analyze_python(py_file)
        return results

    def trace_function(self, file_path: str | Path, function_name: str) -> str:
        path = (self.root / file_path).resolve()
        if not path.exists():
            return f"File not found: {path}"
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return f"Syntax error: {e}"
        target_node: ast.AST | None = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                target_node = node
                break
        if not isinstance(target_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"Function '{function_name}' not found in {path}"
        lines = source.splitlines()
        result: list[str] = []
        result.append(f"Execution trace for {function_name}() in {path}")
        result.append("")
        doc = ast.get_docstring(target_node)
        if doc:
            result.append(f"  Purpose: {doc}")
        result.append("")
        collector = _CallCollector()
        collector.visit(target_node)
        for call in collector.calls:
            line = lines[call.line - 1].strip() if call.line <= len(lines) else ""
            origin = "built-in" if call.is_builtin else "unknown"
            result.append(f"  Line {call.line}: {line}")
            result.append(f"    → calls '{call.name}' ({origin})")
        return "\n".join(result)

    def _analyze_python(self, path: Path) -> AnalysisResult:
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as e:
            return AnalysisResult(file_path=path, language="Python", total_lines=0, summary=f"Read error: {e}")
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            return AnalysisResult(
                file_path=path, language="Python", total_lines=len(lines),
                summary=f"Syntax error: {e}",
            )
        import_tracker = _ImportTracker(self.root, path)
        import_tracker.visit(tree)
        imports = import_tracker.imports
        def_collector = _DefCollector()
        def_collector.visit(tree)
        symbols = def_collector.symbols
        annotated = self._annotate_lines(lines, imports, symbols)
        call_graph: list[tuple[str, str, int]] = []
        for sym in symbols:
            for call in sym.calls:
                call_graph.append((sym.name, call.name, call.line))
        dep_map: dict[str, str] = {}
        for imp in imports:
            dep_map[imp.module] = imp.origin
        deps = sorted(f"{m} ({o})" for m, o in dep_map.items())
        total_lines = len(lines)
        summary_parts: list[str] = []
        summary_parts.append(f"File: {path.name}")
        summary_parts.append("Language: Python")
        summary_parts.append(f"Lines: {total_lines}")
        func_count = sum(1 for s in symbols if s.kind in ("function", "method"))
        class_count = sum(1 for s in symbols if s.kind == "class")
        import_count = len(imports)
        call_count = len(call_graph)
        summary_parts.append(f"Functions/Methods: {func_count}")
        summary_parts.append(f"Classes: {class_count}")
        summary_parts.append(f"Imports: {import_count}")
        summary_parts.append(f"Function calls: {call_count}")
        stdlib_imports = sum(1 for i in imports if i.origin == "stdlib")
        local_imports = sum(1 for i in imports if i.origin == "local")
        third_party = sum(1 for i in imports if i.origin == "third-party")
        summary_parts.append(f"  stdlib: {stdlib_imports} | local: {local_imports} | third-party: {third_party}")
        return AnalysisResult(
            file_path=path,
            language="Python",
            total_lines=total_lines,
            imports=imports,
            symbols=symbols,
            call_graph=call_graph,
            annotated_lines=annotated,
            deps=deps,
            summary="\n".join(summary_parts),
        )

    def _analyze_non_python(self, path: Path) -> AnalysisResult:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return AnalysisResult(file_path=path, language="", total_lines=0, summary=f"Read error: {e}")
        lines = source.splitlines()
        ext_map = {".js": "JavaScript", ".ts": "TypeScript", ".go": "Go", ".rs": "Rust",
                   ".java": "Java", ".c": "C", ".cpp": "C++", ".h": "C", ".hpp": "C++",
                   ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
                   ".kt": "Kotlin", ".scala": "Scala", ".lua": "Lua", ".r": "R",
                   ".sql": "SQL", ".md": "Markdown", ".json": "JSON", ".yaml": "YAML",
                   ".yml": "YAML", ".xml": "XML", ".html": "HTML", ".css": "CSS",
                   ".sh": "Shell", ".bat": "Batch", ".ps1": "PowerShell", ".py": "Python"}
        lang = ext_map.get(path.suffix, "Unknown")
        return AnalysisResult(
            file_path=path, language=lang, total_lines=len(lines),
            summary=f"File: {path.name}\nLanguage: {lang}\nLines: {len(lines)}",
        )

    def _annotate_lines(self, lines: list[str], imports: list[ResolvedImport],
                        symbols: list[SymbolDef]) -> list[AnnotatedLine]:
        import_lines: dict[int, ResolvedImport] = {}
        for imp in imports:
            import_lines[imp.line] = imp
        def_lines: dict[int, SymbolDef] = {}
        call_map: dict[int, list[CalledFunction]] = {}
        for sym in symbols:
            for line_no in range(sym.line, sym.end_line + 1):
                if line_no not in def_lines:
                    def_lines[line_no] = sym
            for call in sym.calls:
                call_map.setdefault(call.line, []).append(call)
        result: list[AnnotatedLine] = []
        for i, line_text in enumerate(lines, start=1):
            al = AnnotatedLine(number=i, code=line_text)
            if i in import_lines:
                imp = import_lines[i]
                al.is_import = True
                if imp.origin == "stdlib":
                    al.origin_info = f"← stdlib: {imp.module}"
                elif imp.origin == "local":
                    rel = ""
                    if imp.source_path:
                        try:
                            rel = f" ({imp.source_path.relative_to(self.root)})"
                        except ValueError:
                            rel = f" ({imp.source_path})"
                    al.origin_info = f"← local{rel}"
                elif imp.origin == "third-party":
                    al.origin_info = "← third-party package"
                else:
                    al.origin_info = "← unknown source"
            if i in def_lines:
                sym = def_lines[i]
                al.is_definition = True
                kind_labels = {"function": "def", "method": "def", "class": "class",
                               "variable": "var", "constant": "const"}
                label = kind_labels.get(sym.kind, sym.kind)
                ctx = f" in {sym.parent}" if sym.parent else ""
                al.explanation = f"definition: {label} `{sym.name}`{ctx}"
                if sym.docstring:
                    al.explanation += f" — {sym.docstring[:80]}"
            if i in call_map:
                al.is_call = True
                targets = [c.name for c in call_map[i]]
                al.call_target = ", ".join(targets[:3])
                if len(targets) > 3:
                    al.call_target += f" ... (+{len(targets) - 3} more)"
                al.explanation = (al.explanation + "; " if al.explanation else "") + f"calls: {al.call_target}"
            result.append(al)
        return result

    def format_explain(self, result: AnalysisResult, show_all: bool = False) -> str:
        output: list[str] = []
        output.append(result.summary)
        output.append("")
        if result.symbols:
            output.append("Symbols:")
            last_kind = ""
            for sym in result.symbols:
                if sym.kind != last_kind:
                    output.append(f"  [{sym.kind}s]")
                    last_kind = sym.kind
                ctx = f" ({sym.parent})" if sym.parent else ""
                decorators = f" @{', '.join(sym.decorators)}" if sym.decorators else ""
                doc = f"  # {sym.docstring[:60]}" if sym.docstring else ""
                output.append(f"    {sym.name}{ctx}{decorators}  line {sym.line}{doc}")
        if result.call_graph:
            output.append("")
            output.append("Call graph (caller → callee):")
            for caller, callee, line in sorted(result.call_graph, key=lambda x: x[2]):
                output.append(f"  {caller} → {callee}  (line {line})")
        if result.annotated_lines:
            output.append("")
            output.append("Line-by-line annotations:")
            for al in result.annotated_lines:
                if not show_all and not al.explanation and not al.origin_info:
                    continue
                line_str = f"  L{al.number:4d} | {al.code.rstrip()}"
                output.append(line_str)
                if al.explanation:
                    output.append(f"         └─ {al.explanation}")
                if al.origin_info:
                    output.append(f"         └─ {al.origin_info}")
        return "\n".join(output)

    def format_analysis(self, results: dict[str, AnalysisResult]) -> str:
        output: list[str] = []
        total_files = len(results)
        total_lines = sum(r.total_lines for r in results.values())
        total_imports = sum(len(r.imports) for r in results.values())
        total_calls = sum(len(r.call_graph) for r in results.values())
        output.append(f"Analysis of {total_files} files ({total_lines} lines, "
                      f"{total_imports} imports, {total_calls} calls)")
        output.append("")
        by_lang: dict[str, int] = {}
        for r in results.values():
            by_lang[r.language] = by_lang.get(r.language, 0) + 1
        output.append("Languages:")
        for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
            output.append(f"  {lang}: {count} files")
        output.append("")
        dep_set: set[str] = set()
        for r in results.values():
            for d in r.deps:
                dep_set.add(d)
        output.append("Dependencies:")
        for dep in sorted(dep_set):
            output.append(f"  {dep}")
        output.append("")
        for _path, result in sorted(results.items()):
            output.append("─" * 50)
            output.append(result.summary)
        return "\n".join(output)
