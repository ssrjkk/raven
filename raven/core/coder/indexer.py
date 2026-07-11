from __future__ import annotations

import ast
import re
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
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".eggs",
    "eggs",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".bzr",
    ".hg",
    ".svn",
    "target",
    "bin",
    "obj",
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
                if entry.is_file() and entry.suffix in LANGUAGE_MAP and not any(part in IGNORE_DIRS for part in entry.relative_to(self._root).parts):
                    results.append(entry)
        except PermissionError as e:
            logger.debug("[indexer] permission denied walking {}: {}", self._root, e)
        return sorted(results)

    def _index_file(self, path: Path) -> CodeFile | None:
        rel = str(path.relative_to(self._root)).replace("\\", "/")
        stat = path.stat()
        language = LANGUAGE_MAP.get(path.suffix, "unknown")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:100000]
        except Exception as e:
            logger.debug("Indexer: skipping unreadable {}: {}", path, e)
            return None

        lines = content.splitlines()
        symbols: list[CodeSymbol] = []

        if language == "python":
            symbols = self._parse_python(content)
        elif language in ("javascript", "typescript"):
            symbols = self._parse_js_ts(content, language)
        elif language == "go":
            symbols = self._parse_go(content)
        elif language == "rust":
            symbols = self._parse_rust(content)
        elif language == "java":
            symbols = self._parse_java(content)
        elif language == "csharp":
            symbols = self._parse_csharp(content)
        elif language == "php":
            symbols = self._parse_php(content)
        elif language == "ruby":
            symbols = self._parse_ruby(content)
        elif language == "lua":
            symbols = self._parse_lua(content)

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
                    symbols.append(
                        CodeSymbol(
                            name=node.name,
                            kind=SymbolKind.CLASS,
                            line=node.lineno or 0,
                            column=node.col_offset or 0,
                            docstring=doc[:200],
                        )
                    )
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            sig = f"def {item.name}({', '.join(a.arg for a in item.args.args if a.arg != 'self')})"
                            doc = ast.get_docstring(item) or ""
                            symbols.append(
                                CodeSymbol(
                                    name=f"{node.name}.{item.name}",
                                    kind=SymbolKind.METHOD,
                                    line=item.lineno or 0,
                                    column=item.col_offset or 0,
                                    docstring=doc[:200],
                                    signature=sig,
                                )
                            )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not any(
                        isinstance(p, ast.ClassDef) for p in ast.walk(tree) if hasattr(p, "body") and node in p.body
                    ):
                        sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
                        doc = ast.get_docstring(node) or ""
                        symbols.append(
                            CodeSymbol(
                                name=node.name,
                                kind=SymbolKind.FUNCTION,
                                line=node.lineno or 0,
                                column=node.col_offset or 0,
                                docstring=doc[:200],
                                signature=sig,
                            )
                        )
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            symbols.append(
                                CodeSymbol(
                                    name=target.id,
                                    kind=SymbolKind.CONSTANT,
                                    line=node.lineno or 0,
                                    column=node.col_offset or 0,
                                )
                            )
        except SyntaxError as e:
            logger.debug("[indexer] syntax error: {}", e)
        return symbols

    def _parse_js_ts(self, content: str, language: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            m = re.match(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?:[*(]\s*)?(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(?:export\s+)?(?:default\s+)?class\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"(?:export\s+)?interface\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:export\s+)?type\s+(\w+)\s*=", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

            m = re.match(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+\*?\s*(\w+)?", stripped)
            if m and m.group(1):
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(?:export\s+)?(?:default\s+)?const\s+(\w+)\s*[=:]", stripped)
            if m:
                rest = stripped[m.end():]
                if "=>" in rest or rest.strip().startswith("async"):
                    symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                elif m.group(1).isupper():
                    symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CONSTANT, line=i))
                else:
                    symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"(?:export\s+)?enum\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

        return symbols

    def _parse_go(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"func\s+(?!\()(\w+)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"type\s+(\w+)\s+struct", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"type\s+(\w+)\s+interface", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:const|var)\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CONSTANT if stripped.startswith("const") else SymbolKind.VARIABLE, line=i))
                continue

        # Second pass: methods (func with receiver)
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            m = re.match(r"func\s+\((\w+\s+\*?\w+)\)\s+(\w+)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(2), kind=SymbolKind.METHOD, line=i, signature=f"({m.group(1)})"))
                continue

        return symbols

    def _parse_rust(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"(?:pub\s+)?(?:unsafe\s+)?fn\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(?:pub\s+)?struct\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"(?:pub\s+)?enum\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

            m = re.match(r"(?:pub\s+)?(?:unsafe\s+)?trait\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:pub\s+)?const\s+(\w+)\s*:", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CONSTANT, line=i))
                continue

            m = re.match(r"(?:pub\s+)?(?:static\s+)?mut?\s+(\w+)\s*:", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"(?:pub\s+)?impl\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"#!\[.*\]", stripped)
            if m:
                continue

            m = re.match(r"(?:pub\s+)?macro_rules!\s+(\w+)", stripped)
            if m:
                continue

        return symbols

    def _parse_csharp(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"(?:public|private|protected|internal|static|abstract|sealed|partial|\s)*\s+(?:abstract\s+|sealed\s+|static\s+)?(?:class|record|struct)\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"(?:public|private|protected|internal)?\s*interface\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|abstract\s+)*(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.METHOD, line=i))
                continue

            m = re.match(r"(?:public|private|protected|internal)\s+(?:static\s+|readonly\s+|const\s+)*(?:\w+(?:\[\])?(?:<[^>]*>)?)\s+(\w+)\s*\{", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"(?:public\s+)?enum\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

        return symbols

    def _parse_php(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"(?:abstract\s+|final\s+)?(?:class|trait)\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"interface\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:public|private|protected)\s+(?:static\s+|abstract\s+)?function\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.METHOD, line=i))
                continue

            m = re.match(r"function\s+(\w+)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(?:public|private|protected)\s+(?:static\s+)?(?:readonly\s+)?(?:int|float|string|bool|array|void|\w+)\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"enum\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

        return symbols

    def _parse_ruby(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"class\s+(?:<<\s+)?(\w+(?:::\w+)*)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"module\s+(\w+(?:::\w+)*)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"def\s+(?:self\.)?(\w+(?:[?!])?)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.METHOD, line=i))
                continue

            m = re.match(r"(\w+)\s*=\s*(?:->|lambda|proc\b)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(\w+)\s*=\s*", stripped)
            if m and m.group(1).isupper():
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CONSTANT, line=i))
                continue

            m = re.match(r"attr_(?:reader|writer|accessor)\s+(?::)?(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

        return symbols

    def _parse_lua(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"(?:local\s+)?function\s+(\w+(?:[.:]\w+)*)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(\w+(?:[.:]\w+)*)\s*=\s*function\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.FUNCTION, line=i))
                continue

            m = re.match(r"(\w+(?:[.:]\w+)*)\s*=\s*\{", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"local\s+(\w+)\s*=", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.VARIABLE, line=i))
                continue

            m = re.match(r"(\w+(?:[.:]\w+)*)\s*=\s*(?:true|false|\d+)", stripped)
            if m and m.group(1).isupper():
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CONSTANT, line=i))
                continue

        return symbols

    def _parse_java(self, content: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            m = re.match(r"(?:public|private|protected|static|abstract|final|sealed|non-sealed|\s)*\s+(?:abstract\s+|final\s+|sealed\s+)?(?:static\s+)?(?:class|record)\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.CLASS, line=i))
                continue

            m = re.match(r"(?:public\s+)?interface\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.INTERFACE, line=i))
                continue

            m = re.match(r"(?:public|private|protected)\s+(?:static\s+|abstract\s+|final\s+|synchronized\s+)*(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.METHOD, line=i))
                continue

            m = re.match(r"(?:public|private|protected)\s+(?:static\s+|final\s+)*(?:\w+(?:\[\])?(?:<[^>]*>)?)\s+(\w+)\s*(?:=|;)", stripped)
            if m:
                kind = SymbolKind.CONSTANT if m.group(1).isupper() else SymbolKind.VARIABLE
                symbols.append(CodeSymbol(name=m.group(1), kind=kind, line=i))
                continue

            m = re.match(r"(?:public\s+)?enum\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

            m = re.match(r"@interface\s+(\w+)", stripped)
            if m:
                symbols.append(CodeSymbol(name=m.group(1), kind=SymbolKind.TYPE, line=i))
                continue

        return symbols

    async def index_async(self, max_files: int = 5000) -> dict[str, CodeFile]:
        self.index(max_files)
        await self._lsp_enrich()
        return self._files

    async def _lsp_enrich(self) -> None:
        supported = {"python", "typescript", "javascript", "go", "rust", "java", "csharp", "php", "ruby", "lua"}
        lang_files: dict[str, list[Path]] = {}
        root = self._root
        for rel_path, cf in self._files.items():
            if cf.language in supported:
                lang_files.setdefault(cf.language, []).append(root / rel_path)

        if not lang_files:
            return

        for lang, paths in lang_files.items():
            try:
                from ravencode.runtime.lsp import LSPClient

                client = LSPClient(lang, root_uri=f"file://{root.as_posix()}")
                try:
                    await client.start()
                except (FileNotFoundError, ValueError) as exc:
                    logger.debug("[indexer] LSP not available for {}: {}", lang, exc)
                    continue

                for fp in paths:
                    try:
                        uri = f"file://{fp.as_posix()}"
                        symbols = await client.document_symbols(uri)
                        if not symbols:
                            continue
                        rel = str(fp.relative_to(root)).replace("\\", "/")
                        code_file = self._files.get(rel)
                        if code_file is None:
                            continue
                        lsp_symbols: list[CodeSymbol] = []
                        for s in symbols:
                            kind = self._lsp_kind_to_symbol_kind(s.get("kind", 0))
                            lsp_symbols.append(
                                CodeSymbol(
                                    name=s.get("name", ""),
                                    kind=kind,
                                    line=0,
                                    column=0,
                                    signature=s.get("detail", ""),
                                )
                            )
                            children = s.get("children", [])
                            for child in children[:10]:
                                child_kind = self._lsp_kind_to_symbol_kind(child.get("kind", 0))
                                lsp_symbols.append(
                                    CodeSymbol(
                                        name=child.get("name", ""),
                                        kind=child_kind,
                                        line=0,
                                        column=0,
                                    )
                                )
                        if lsp_symbols:
                            code_file.symbols = lsp_symbols
                    except Exception as e:
                        logger.debug("[indexer] LSP enrich failed for {}: {}", fp, e)

                await client.stop()
            except Exception as exc:
                logger.debug("[indexer] LSP enrich error for {}: {}", lang, exc)

    @staticmethod
    def _lsp_kind_to_symbol_kind(lsp_kind: int) -> SymbolKind:
        mapping = {
            1: SymbolKind.VARIABLE, 2: SymbolKind.VARIABLE, 3: SymbolKind.VARIABLE,
            4: SymbolKind.VARIABLE, 5: SymbolKind.CLASS, 6: SymbolKind.METHOD,
            7: SymbolKind.VARIABLE, 8: SymbolKind.VARIABLE, 9: SymbolKind.METHOD,
            10: SymbolKind.TYPE, 11: SymbolKind.INTERFACE, 12: SymbolKind.FUNCTION,
            13: SymbolKind.VARIABLE, 14: SymbolKind.CONSTANT, 22: SymbolKind.CONSTANT,
            23: SymbolKind.CLASS, 24: SymbolKind.VARIABLE,
        }
        return mapping.get(lsp_kind, SymbolKind.FUNCTION)

    def _language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cf in self._files.values():
            counts[cf.language] = counts.get(cf.language, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))
