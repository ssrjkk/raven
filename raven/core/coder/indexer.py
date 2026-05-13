from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.coder.models import CodeFile, CodeSymbol, SymbolKind

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".eggs", "eggs", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", "dist", "build", ".idea", ".vscode",
    ".bzr", ".hg", ".svn", "target", "bin", "obj",
}


class CodeIndexer:
    def __init__(self, root_path: str):
        self._root = Path(root_path).resolve()
        self._files: dict[str, CodeFile] = {}
        self._index: dict[str, list[str]] = {}  # term -> file paths
        self._last_indexed: float = 0.0

    def index(self, max_files: int = 5000) -> dict[str, CodeFile]:
        self._files = {}
        self._index = {}

        for i, file_path in enumerate(self._walk()):
            if i >= max_files:
                break
            try:
                cf = self._index_file(file_path)
                if cf:
                    self._files[cf.path] = cf
                    for sym in cf.symbols:
                        for token in sym.name.split("."):
                            self._index.setdefault(token.lower(), []).append(cf.path)
            except Exception as e:
                logger.debug("Indexer: skipped {} ({})", file_path, e)

        self._last_indexed = time.time()
        logger.info("Indexed {} files from {}", len(self._files), self._root)
        return self._files

    def search(self, query: str, max_results: int = 20) -> list[CodeFile]:
        terms = query.lower().split()
        if not terms:
            return []

        matched_paths: set[str] | None = None
        for term in terms:
            paths = set(self._index.get(term, []))
            if matched_paths is None:
                matched_paths = paths
            else:
                matched_paths &= paths

        if not matched_paths:
            return list(self._files.values())[:max_results]

        results = [self._files[p] for p in matched_paths if p in self._files]
        return results[:max_results]

    def get_file(self, rel_path: str) -> CodeFile | None:
        return self._files.get(rel_path)

    def summary(self) -> dict[str, Any]:
        return {
            "root": str(self._root),
            "files": len(self._files),
            "last_indexed": self._last_indexed,
            "languages": self._language_counts(),
        }

    def _walk(self) -> list[Path]:
        results = []
        try:
            for entry in self._root.rglob("*"):
                if entry.is_file() and entry.suffix in LANGUAGE_MAP:
                    if not any(part in IGNORE_DIRS for part in entry.relative_to(self._root).parts):
                        results.append(entry)
        except PermissionError:
            pass
        return sorted(results)

    def _index_file(self, path: Path) -> CodeFile | None:
        rel = str(path.relative_to(self._root)).replace("\\", "/")
        stat = path.stat()
        language = LANGUAGE_MAP.get(path.suffix, "unknown")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:100000]
        except Exception:
            return None

        lines = content.splitlines()
        symbols: list[CodeSymbol] = []

        if language == "python":
            symbols = self._parse_python(content)

        return CodeFile(
            path=rel,
            language=language,
            size=stat.st_size,
            lines=len(lines),
            modified_at=stat.st_mtime,
            symbols=symbols,
            content_preview="\n".join(lines[:30]) if lines else "",
        )

    def _parse_python(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node) or ""
                    symbols.append(CodeSymbol(
                        name=node.name, kind=SymbolKind.CLASS,
                        line=node.lineno or 0, column=node.col_offset or 0,
                        docstring=doc[:200],
                    ))
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            sig = f"def {item.name}({', '.join(a.arg for a in item.args.args if a.arg != 'self')})"
                            doc = ast.get_docstring(item) or ""
                            symbols.append(CodeSymbol(
                                name=f"{node.name}.{item.name}", kind=SymbolKind.METHOD,
                                line=item.lineno or 0, column=item.col_offset or 0,
                                docstring=doc[:200], signature=sig,
                            ))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree) if hasattr(p, 'body') and node in p.body):
                        sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
                        doc = ast.get_docstring(node) or ""
                        symbols.append(CodeSymbol(
                            name=node.name, kind=SymbolKind.FUNCTION,
                            line=node.lineno or 0, column=node.col_offset or 0,
                            docstring=doc[:200], signature=sig,
                        ))
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            symbols.append(CodeSymbol(
                                name=target.id, kind=SymbolKind.CONSTANT,
                                line=node.lineno or 0, column=node.col_offset or 0,
                            ))
        except SyntaxError:
            pass
        return symbols

    def _language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cf in self._files.values():
            counts[cf.language] = counts.get(cf.language, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))
