from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from loguru import logger

_LSP_SERVERS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls", "serve"],
    "rust": ["rust-analyzer"],
    "java": ["jdtls"],
    "csharp": ["omnisharp"],
    "php": ["phpactor", "language-server"],
    "ruby": ["solargraph", "stdio"],
    "lua": ["lua-language-server"],
}


class LSPClient:
    def __init__(self, language: str, root_uri: str | None = None) -> None:
        self.language = language
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._root_uri = root_uri or f"file://{Path.cwd().as_posix()}"

    async def start(self) -> None:
        cmd = _LSP_SERVERS.get(self.language)
        if not cmd:
            raise ValueError(f"No LSP server configured for language: {self.language}")
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ValueError(f"LSP server not found for language: {self.language}") from exc
        asyncio.create_task(self._reader())
        await self._send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": self._root_uri,
                "capabilities": {},
            },
        })
        await self._send({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        })

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("LSP not connected")
        body = json.dumps(msg, ensure_ascii=False)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        self._process.stdin.write((header + body).encode("utf-8"))
        await self._process.stdin.drain()

    async def _reader(self) -> None:
        buf = b""
        while self._process and self._process.stdout:
            chunk = await self._process.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\r\n\r\n" in buf:
                header, _, rest = buf.partition(b"\r\n\r\n")
                try:
                    cline = header.decode("utf-8")
                    length = int([h for h in cline.split("\r\n") if h.startswith("Content-Length")][0].split(":")[1])
                except (IndexError, ValueError, UnicodeDecodeError):
                    buf = rest
                    continue
                if len(rest) < length:
                    break
                body = rest[:length].decode("utf-8")
                buf = rest[length:]
                try:
                    msg = json.loads(body)
                    rid = msg.get("id")
                    if rid is not None and rid in self._pending:
                        self._pending[rid].set_result(msg)
                except json.JSONDecodeError:
                    continue

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        rid = self._request_id
        fut: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout=30)
        except TimeoutError as exc:
            raise TimeoutError(f"LSP request {method} timed out") from exc

    async def completion(self, uri: str, line: int, col: int) -> list[str]:
        result = await self._request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": col},
        })
        items = (result.get("result") or {}).get("items", [])
        return [i.get("label", "") for i in items[:20]]

    async def definition(self, uri: str, line: int, col: int) -> list[dict[str, Any]]:
        result = await self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": col},
        })
        locs = result.get("result", [])
        if isinstance(locs, dict):
            locs = [locs]
        return [
            {"uri": loc.get("uri", ""), "line": loc.get("range", {}).get("start", {}).get("line", 0)}
            for loc in locs[:5]
        ]

    async def references(self, uri: str, line: int, col: int) -> list[dict[str, Any]]:
        result = await self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": col},
            "context": {"includeDeclaration": True},
        })
        locs = result.get("result", [])
        return [
            {"uri": loc.get("uri", ""), "line": loc.get("range", {}).get("start", {}).get("line", 0)}
            for loc in locs[:20]
        ]

    async def hover(self, uri: str, line: int, col: int) -> str:
        result = await self._request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": col},
        })
        contents = (result.get("result") or {}).get("contents", {})
        if isinstance(contents, dict):
            val = contents.get("value", "")
            return str(val) if val is not None else ""
        return str(contents)

    async def document_symbols(self, uri: str) -> list[dict[str, Any]]:
        result = await self._request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        symbols = result.get("result", [])
        out = []
        for s in symbols:
            if isinstance(s, dict):
                kind = s.get("kind", 0)
                name = s.get("name", "")
                detail = s.get("detail", "")
                entry = {"name": name, "kind": kind, "detail": detail}
                children = s.get("children", [])
                if children:
                    entry["children"] = [
                        {"name": c.get("name", ""), "kind": c.get("kind", 0)}
                        for c in children[:10]
                    ]
                out.append(entry)
        return out[:30]

    async def stop(self) -> None:
        if self._process:
            self._process.kill()
            await self._process.wait()


_lsp_clients: dict[str, LSPClient] = {}


async def _get_lsp(language: str) -> LSPClient:
    if language not in _lsp_clients:
        client = LSPClient(language)
        try:
            await client.start()
        except (FileNotFoundError, ValueError) as exc:
            raise RuntimeError(f"Cannot start LSP for {language}: {exc}") from exc
        _lsp_clients[language] = client
    return _lsp_clients[language]


async def lsp_completion(path: str, line: int, col: int) -> str:
    lang = _detect_lang(path)
    try:
        client = await _get_lsp(lang)
        uri = f"file://{Path(path).resolve().as_posix()}"
        items = await client.completion(uri, line, col)
        return "\n".join(items) if items else "(no completions)"
    except Exception as exc:
        return f"[error] lsp_completion: {exc}"


async def lsp_definition(path: str, line: int, col: int) -> str:
    lang = _detect_lang(path)
    try:
        client = await _get_lsp(lang)
        uri = f"file://{Path(path).resolve().as_posix()}"
        defs = await client.definition(uri, line, col)
        if not defs:
            return "(no definition found)"
        return "\n".join(f"{d['uri']}:{d['line']}" for d in defs)
    except Exception as exc:
        return f"[error] lsp_definition: {exc}"


async def lsp_references(path: str, line: int, col: int) -> str:
    lang = _detect_lang(path)
    try:
        client = await _get_lsp(lang)
        uri = f"file://{Path(path).resolve().as_posix()}"
        refs = await client.references(uri, line, col)
        if not refs:
            return "(no references found)"
        return "\n".join(f"{d['uri']}:{d['line']}" for d in refs)
    except Exception as exc:
        return f"[error] lsp_references: {exc}"


async def lsp_hover(path: str, line: int, col: int) -> str:
    lang = _detect_lang(path)
    try:
        client = await _get_lsp(lang)
        uri = f"file://{Path(path).resolve().as_posix()}"
        result = await client.hover(uri, line, col)
        return result or "(no info)"
    except Exception as exc:
        return f"[error] lsp_hover: {exc}"


def _detect_lang(path: str) -> str:
    ext = Path(path).suffix.lower()
    lang_map: dict[str, str] = {
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".cs": "csharp",
        ".php": "php",
        ".phtml": "php",
        ".rb": "ruby",
        ".erb": "ruby",
        ".lua": "lua",
    }
    return lang_map.get(ext, "python")


# ---------------------------------------------------------------------------
# LSP auto-enrichment — gather project symbols for LLM context
# ---------------------------------------------------------------------------

_SYMBOL_KIND_NAMES: dict[int, str] = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
    6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
    11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
    15: "String", 16: "Number", 17: "Boolean", 18: "Array", 19: "Object",
    20: "Key", 21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}


async def enrich_context(project_root: str | Path | None = None, max_files: int = 10) -> str:
    root = Path(project_root or Path.cwd()).resolve()
    if not root.is_dir():
        return "(project root not found)"

    extensions = await asyncio.to_thread(_scan_extensions, root)
    if not extensions:
        return "(no source files found in project)"

    top_langs = [ext for ext, _ in Counter(extensions).most_common(5)]
    active_languages = set()
    for ext in top_langs:
        lang = _ext_to_lang(ext)
        if lang:
            active_languages.add(lang)

    parts = [f"Project: {root.name}", f"Root: {root}"]
    if active_languages:
        parts.append(f"Languages detected: {', '.join(sorted(active_languages))}")

    for lang in sorted(active_languages):
        try:
            client = await _get_lsp(lang)
        except (RuntimeError, FileNotFoundError, ValueError):
            parts.append(f"[LSP {lang}: server not available]")
            continue

        lang_exts = [e for e in _LANG_EXTS.get(lang, [])]
        files = await asyncio.to_thread(_find_key_files, root, lang_exts, max_files)
        if not files:
            continue

        file_symbols: list[str] = []
        for fp in files:
            uri = f"file://{fp.as_posix()}"
            try:
                symbols = await client.document_symbols(uri)
                if symbols:
                    names = []
                    for s in symbols:
                        kind_name = _SYMBOL_KIND_NAMES.get(s["kind"], "?")
                        label = f"{s['name']} ({kind_name})"
                        children = s.get("children")
                        if children:
                            child_names = ", ".join(c["name"] for c in children[:5])
                            label += f" {{{child_names}}}"
                        names.append(label)
                    file_symbols.append(f"  {fp.relative_to(root)}: {', '.join(names[:10])}")
            except Exception as e:
                logger.debug("LSP symbol parse failed for {}: {}", fp, e)
                file_symbols.append(f"  {fp.relative_to(root)}: (symbols unavailable)")

        if file_symbols:
            parts.append(f"\n[{lang}]")
            parts.extend(file_symbols)

    return "\n".join(parts)


def _scan_extensions(root: Path) -> list[str]:
    exts = []
    try:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in _LANG_EXTS_FLAT:
                exts.append(p.suffix.lower())
    except PermissionError as e:
        logger.debug("[lsp] permission denied scanning {}: {}", root, e)
    return exts


def _ext_to_lang(ext: str) -> str | None:
    for lang, exts in _LANG_EXTS.items():
        if ext in exts:
            return lang
    return None


def _find_key_files(root: Path, exts: list[str], max_files: int) -> list[Path]:
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            depth = len(p.relative_to(root).parts)
            files.append((depth, p))
    files.sort(key=lambda x: (x[0], x[1].stat().st_size))
    return [p for _, p in files[:max_files]]


_LANG_EXTS: dict[str, list[str]] = {
    "python": [".py", ".pyi"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
    "csharp": [".cs"],
    "php": [".php", ".phtml"],
    "ruby": [".rb", ".erb"],
    "lua": [".lua"],
}

_LANG_EXTS_FLAT: set[str] = {e for exts in _LANG_EXTS.values() for e in exts}
