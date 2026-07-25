from __future__ import annotations

import asyncio
import json
import time
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

_DIAG_CACHE_TTL = 30.0


class LSPClient:
    def __init__(self, language: str, root_uri: str | None = None) -> None:
        self.language = language
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._root_uri = root_uri or f"file://{Path.cwd().as_posix()}"
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._diag_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._cmd = _LSP_SERVERS.get(language)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            if not self._cmd:
                msg = f"No LSP server configured for language: {self.language}"
                raise ValueError(msg)
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self._cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                msg = f"LSP server not found for: {self.language}"
                raise ValueError(msg) from exc
            reader_task = asyncio.create_task(self._reader())
            self._bg_tasks.add(reader_task)
            reader_task.add_done_callback(self._bg_tasks.discard)
            await self._send({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"processId": None, "rootUri": self._root_uri, "capabilities": {}},
            })
            await self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            self._initialized = True

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
                    length = int(next(h for h in cline.split("\r\n") if h.startswith("Content-Length")).split(":")[1])
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
                    elif msg.get("method") == "textDocument/publishDiagnostics":
                        uri = msg.get("params", {}).get("uri", "")
                        diags = msg.get("params", {}).get("diagnostics", [])
                        if uri:
                            self._diag_cache[uri] = (time.monotonic(), diags)
                except json.JSONDecodeError:
                    continue

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_initialized()
        self._request_id += 1
        rid = self._request_id
        fut: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout=30)
        except TimeoutError as exc:
            msg = f"LSP request {method} timed out"
            raise TimeoutError(msg) from exc

    async def diagnostics(self, uri: str) -> list[dict[str, Any]]:
        cached = self._diag_cache.get(uri)
        if cached and (time.monotonic() - cached[0]) < _DIAG_CACHE_TTL:
            return cached[1]
        try:
            result: Any = await self._request("textDocument/diagnostic", {
                "textDocument": {"uri": uri},
            })
            items: list[dict[str, Any]] = result.get("result", {}).get("items", [])
            self._diag_cache[uri] = (time.monotonic(), items)
            return items
        except Exception:
            prev = self._diag_cache.get(uri)
            return prev[1] if prev else []

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
        contents = (result.get("result") or {}).get("contents", "")
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            val = contents.get("value")
            return str(val) if val is not None else ""
        if isinstance(contents, list) and contents:
            first = contents[0]
            if isinstance(first, dict):
                val = first.get("value")
                return str(val) if val is not None else ""
            return str(first)
        return str(contents)

    async def start(self) -> None:
        await self._ensure_initialized()

    async def document_symbols(self, uri: str) -> list[dict[str, Any]]:
        try:
            result = await self._request("textDocument/documentSymbol", {
                "textDocument": {"uri": uri},
            })
            symbols = result.get("result", [])
            out: list[dict[str, Any]] = []
            for s in symbols:
                if isinstance(s, dict):
                    out.append({
                        "name": s.get("name", ""),
                        "kind": s.get("kind", 0),
                        "detail": s.get("detail", ""),
                        "range": s.get("range", {}),
                    })
            return out
        except Exception:
            return []

    async def stop(self) -> None:
        for task in self._bg_tasks:
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                    await self._process.wait()
                except ProcessLookupError:
                    pass
        self._initialized = False


class LSPPool:
    def __init__(self) -> None:
        self._clients: dict[str, LSPClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, language: str, root_uri: str | None = None) -> LSPClient | None:
        async with self._lock:
            if language not in self._clients:
                try:
                    self._clients[language] = LSPClient(language, root_uri)
                except ValueError:
                    return None
            return self._clients[language]

    async def diagnostics(self, file_path: str, language: str) -> list[dict[str, Any]]:
        client = await self.get(language)
        if not client:
            return []
        uri = f"file://{Path(file_path).as_posix()}"
        return await client.diagnostics(uri)

    async def stop_all(self) -> None:
        async with self._lock:
            for lang, client in self._clients.items():
                try:
                    await client.stop()
                except Exception as e:
                    logger.debug("LSP stop error [{}]: {}", lang, e)
            self._clients.clear()


_lsp_pool = LSPPool()


def get_lsp_pool() -> LSPPool:
    return _lsp_pool


async def lsp_completion(path: str, line: int, col: int) -> str:
    lang = _detect_language(path)
    client = await _lsp_pool.get(lang)
    if not client:
        return ""
    uri = f"file://{Path(path).as_posix()}"
    items = await client.completion(uri, line, col)
    return "\n".join(items) if items else ""


async def lsp_definition(path: str, line: int, col: int) -> str:
    lang = _detect_language(path)
    client = await _lsp_pool.get(lang)
    if not client:
        return ""
    uri = f"file://{Path(path).as_posix()}"
    locs = await client.definition(uri, line, col)
    return "\n".join(f"{loc['uri']}:{loc['line']}" for loc in locs) if locs else ""


async def lsp_references(path: str, line: int, col: int) -> str:
    lang = _detect_language(path)
    client = await _lsp_pool.get(lang)
    if not client:
        return ""
    uri = f"file://{Path(path).as_posix()}"
    locs = await client.references(uri, line, col)
    return "\n".join(f"{loc['uri']}:{loc['line']}" for loc in locs) if locs else ""


async def lsp_hover(path: str, line: int, col: int) -> str:
    lang = _detect_language(path)
    client = await _lsp_pool.get(lang)
    if not client:
        return ""
    uri = f"file://{Path(path).as_posix()}"
    return await client.hover(uri, line, col)


_LANG_EXTS: dict[str, list[str]] = {
    "python": [".py", ".pyi"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
    "csharp": [".cs"],
    "php": [".php"],
    "ruby": [".rb"],
}


def _ext_to_lang(ext: str) -> str | None:
    for lang, exts in _LANG_EXTS.items():
        if ext in exts:
            return lang
    return None


def _scan_extensions(root: Path) -> list[str]:
    exts: list[str] = []
    try:
        for fp in root.rglob("*"):
            if fp.is_file() and fp.suffix:
                exts.append(fp.suffix.lower())
    except PermissionError:
        pass
    return exts


def _find_key_files(root: Path, exts: list[str], max_files: int) -> list[Path]:
    files: list[Path] = []
    try:
        for fp in root.rglob("*"):
            if fp.is_file() and fp.suffix.lower() in exts:
                files.append(fp)
                if len(files) >= max_files:
                    break
    except PermissionError:
        pass
    return files





async def enrich_context(project_root: str | Path | None = None, max_files: int = 10) -> str:
    root = Path(project_root or Path.cwd()).resolve()
    if not root.is_dir():
        return "(project root not found)"
    exts = await asyncio.to_thread(_scan_extensions, root)
    if not exts:
        return "(no source files found in project)"
    top_exts = [ext for ext, _ in Counter(exts).most_common(5)]
    active_langs: set[str] = set()
    for ext in top_exts:
        lang = _ext_to_lang(ext)
        if lang:
            active_langs.add(lang)
    parts: list[str] = [f"Project: {root.name}", f"Root: {root}"]
    if active_langs:
        parts.append(f"Languages detected: {', '.join(sorted(active_langs))}")
    for lang in sorted(active_langs):
        client = await _lsp_pool.get(lang)
        if not client:
            parts.append(f"[LSP {lang}: server not available]")
            continue
        lang_exts = _LANG_EXTS.get(lang, [])
        files = await asyncio.to_thread(_find_key_files, root, lang_exts, max_files)
        if not files:
            continue
        file_parts: list[str] = []
        for fp in files:
            uri = f"file://{fp.as_posix()}"
            diags = await client.diagnostics(uri)
            if diags:
                file_parts.append(f"\n  {fp.relative_to(root)}:")
                for d in diags[:5]:
                    line_num = d.get("range", {}).get("start", {}).get("line", 0)
                    msg = d.get("message", "")
                    sev = d.get("severity", 1)
                    label = {1: "ERROR", 2: "WARNING", 3: "INFO", 4: "HINT"}.get(sev, "NOTE")
                    file_parts.append(f"    {label} L{line_num}: {msg}")
        if file_parts:
            parts.append(f"\n[{lang}]" + "".join(file_parts))
    if len(parts) <= 2:
        return "(no LSP diagnostics found)"
    return "\n".join(parts)


def _detect_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    mapping = {
        ".py": "python", ".pyi": "python",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".cs": "csharp",
        ".php": "php",
        ".rb": "ruby",
        ".lua": "lua",
    }
    return mapping.get(ext, "python")
