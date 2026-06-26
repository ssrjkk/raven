from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

_LSP_SERVERS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls", "serve"],
    "rust": ["rust-analyzer"],
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
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
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
    }
    return lang_map.get(ext, "python")
