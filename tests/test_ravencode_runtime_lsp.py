from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.runtime.lsp as lsp_mod
from ravencode.runtime.lsp import (
    LSPClient,
    LSPPool,
    _detect_language,
    _ext_to_lang,
    _find_key_files,
    _scan_extensions,
    enrich_context,
    get_lsp_pool,
    lsp_completion,
    lsp_definition,
    lsp_hover,
    lsp_references,
)


def _frame(body: str) -> bytes:
    return f"Content-Length: {len(body.encode())}\r\n\r\n{body}".encode()


def _fake_proc(stdout_chunks: list[bytes] | None = None) -> Any:
    proc = SimpleNamespace()
    proc.stdin = SimpleNamespace(write=MagicMock(), drain=AsyncMock())
    proc.stdout = SimpleNamespace(read=AsyncMock(side_effect=stdout_chunks or [b""]))
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


class TestClientInit:
    def test_default_root_uri(self) -> None:
        client = LSPClient("python")
        assert client.language == "python"
        assert client._root_uri.startswith("file://")
        assert client._cmd == ["pyright-langserver", "--stdio"]

    def test_custom_root_uri(self) -> None:
        assert LSPClient("go", root_uri="file:///ws")._root_uri == "file:///ws"

    def test_unknown_language_no_cmd(self) -> None:
        assert LSPClient("cobol")._cmd is None


class TestEnsureInitialized:
    async def test_no_server_for_language(self) -> None:
        client = LSPClient("cobol")
        with pytest.raises(ValueError, match="No LSP server configured"):
            await client._ensure_initialized()

    async def test_file_not_found(self, monkeypatch) -> None:
        client = LSPClient("python")
        monkeypatch.setattr(
            "ravencode.runtime.lsp.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError()),
        )
        with pytest.raises(ValueError, match="LSP server not found"):
            await client._ensure_initialized()

    async def test_initializes(self, monkeypatch) -> None:
        client = LSPClient("python")
        writes: list[bytes] = []
        proc: Any = SimpleNamespace(
            stdin=SimpleNamespace(
                write=MagicMock(side_effect=lambda d: writes.append(d)), drain=AsyncMock()
            ),
            stdout=SimpleNamespace(read=AsyncMock(side_effect=[b""])),
            terminate=MagicMock(),
            kill=MagicMock(),
            wait=AsyncMock(return_value=0),
        )
        monkeypatch.setattr(
            "ravencode.runtime.lsp.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        )
        await client._ensure_initialized()
        assert client._initialized is True
        assert client._process is proc
        assert len(writes) == 2
        await client.stop()

    async def test_already_initialized(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._initialized = True
        exec_mock = AsyncMock()
        monkeypatch.setattr("ravencode.runtime.lsp.asyncio.create_subprocess_exec", exec_mock)
        await client._ensure_initialized()
        exec_mock.assert_not_awaited()

    async def test_inner_double_check(self) -> None:
        client = LSPClient("python")

        class FakeLock:
            async def __aenter__(self) -> None:
                client._initialized = True

            async def __aexit__(self, *exc) -> bool:
                return False

        fake_lock: Any = FakeLock()
        client._init_lock = fake_lock
        await client._ensure_initialized()
        assert client._initialized is True


class TestSend:
    async def test_not_connected(self) -> None:
        client = LSPClient("python")
        with pytest.raises(RuntimeError, match="LSP not connected"):
            await client._send({})

    async def test_writes_frame(self) -> None:
        client = LSPClient("python")
        proc = _fake_proc()
        client._process = proc
        await client._send({"jsonrpc": "2.0", "id": 1})
        written = proc.stdin.write.call_args[0][0].decode("utf-8")
        assert "Content-Length: " in written
        assert '"id": 1' in written


class TestReader:
    async def test_resolves_pending(self) -> None:
        client = LSPClient("python")
        proc = _fake_proc([_frame('{"id": 7, "result": {"ok": true}}'), b""])
        client._process = proc
        fut: asyncio.Future[dict[str, Any]] = asyncio.Future()
        client._pending[7] = fut
        await client._reader()
        assert fut.done()
        assert fut.result()["result"]["ok"] is True

    async def test_caches_diagnostics(self) -> None:
        client = LSPClient("python")
        body = '{"method": "textDocument/publishDiagnostics", "params": {"uri": "file:///a.py", "diagnostics": [{"message": "x"}]}}'
        proc = _fake_proc([_frame(body), b""])
        client._process = proc
        await client._reader()
        assert "file:///a.py" in client._diag_cache

    async def test_bad_header_resets(self) -> None:
        client = LSPClient("python")
        proc = _fake_proc([b"Content-Length: abc\r\n\r\n{\"a\":1}", b""])
        client._process = proc
        await client._reader()

    async def test_invalid_json_continues(self) -> None:
        client = LSPClient("python")
        body = "not json"
        frame = _frame(body)
        proc = _fake_proc([frame, b""])
        client._process = proc
        await client._reader()

    async def test_truncated_body_breaks(self) -> None:
        client = LSPClient("python")
        body = '{"id": 9, "x": "aaaaaaaa"}'
        head = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n".encode()
        proc = _fake_proc([head + body[:3].encode("utf-8"), b""])
        client._process = proc
        await client._reader()

    async def test_multiple_messages_in_chunk(self) -> None:
        client = LSPClient("python")
        fut: asyncio.Future[dict[str, object]] = asyncio.Future()
        client._pending[1] = fut
        chunk = _frame('{"id": 1, "result": {}}') + _frame('{"id": 2, "result": {}}')
        proc = _fake_proc([chunk, b""])
        client._process = proc
        await client._reader()
        assert fut.done()


class TestRequest:
    async def test_success(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._initialized = True
        client._process = _fake_proc()
        monkeypatch.setattr("ravencode.runtime.lsp.asyncio.wait_for", AsyncMock(return_value={"result": {}}))
        result = await client._request("textDocument/diagnostic", {})
        assert result == {"result": {}}
        assert client._request_id == 1

    async def test_timeout(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._initialized = True
        client._process = _fake_proc()

        async def raise_timeout(fut, timeout):
            raise TimeoutError()

        monkeypatch.setattr("ravencode.runtime.lsp.asyncio.wait_for", raise_timeout)
        with pytest.raises(TimeoutError, match="timed out"):
            await client._request("textDocument/diagnostic", {})


class TestClientMethods:
    def _client(self, monkeypatch, request_result: dict[str, Any]) -> LSPClient:
        client = LSPClient("python")
        client._initialized = True
        client._process = _fake_proc()
        async def fake_request(method, params):
            return request_result
        client._request = fake_request  # type: ignore[method-assign]
        return client

    async def test_diagnostics_cached_fresh(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._diag_cache["u"] = (float("inf"), [{"m": "old"}])
        assert await client.diagnostics("u") == [{"m": "old"}]

    async def test_diagnostics_request(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"items": [{"message": "e1"}]}})
        assert await client.diagnostics("u") == [{"message": "e1"}]
        assert "u" in client._diag_cache

    async def test_diagnostics_error_falls_back(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._diag_cache["u"] = (0.0, [{"m": "prev"}])
        async def fail(method, params):
            raise RuntimeError("boom")
        client._request = fail  # type: ignore[method-assign]
        assert await client.diagnostics("u") == [{"m": "prev"}]

    async def test_diagnostics_error_no_cache(self, monkeypatch) -> None:
        client = LSPClient("python")
        async def fail(method, params):
            raise RuntimeError("boom")
        client._request = fail  # type: ignore[method-assign]
        assert await client.diagnostics("u") == []

    async def test_completion(self, monkeypatch) -> None:
        client = self._client(
            monkeypatch,
            {"result": {"items": [{"label": "foo"}, {"label": "bar"}, {"label": "baz"}]}},
        )
        assert await client.completion("u", 1, 2) == ["foo", "bar", "baz"]

    async def test_definition_list(self, monkeypatch) -> None:
        loc = {"uri": "file:///a.py", "range": {"start": {"line": 5}}}
        client = self._client(monkeypatch, {"result": [loc]})
        assert await client.definition("u", 0, 0) == [{"uri": "file:///a.py", "line": 5}]

    async def test_definition_dict(self, monkeypatch) -> None:
        loc = {"uri": "file:///a.py", "range": {"start": {"line": 5}}}
        client = self._client(monkeypatch, {"result": loc})
        assert await client.definition("u", 0, 0) == [{"uri": "file:///a.py", "line": 5}]

    async def test_references(self, monkeypatch) -> None:
        loc = {"uri": "file:///a.py", "range": {"start": {"line": 3}}}
        client = self._client(monkeypatch, {"result": [loc]})
        assert await client.references("u", 0, 0) == [{"uri": "file:///a.py", "line": 3}]

    async def test_hover_string(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": "doc text"}})
        assert await client.hover("u", 0, 0) == "doc text"

    async def test_hover_dict(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": {"value": "v"}}})
        assert await client.hover("u", 0, 0) == "v"

    async def test_hover_dict_none_value(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": {"value": None}}})
        assert await client.hover("u", 0, 0) == ""

    async def test_hover_list(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": [{"value": "first"}, "second"]}})
        assert await client.hover("u", 0, 0) == "first"

    async def test_hover_list_str(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": ["plain"]}})
        assert await client.hover("u", 0, 0) == "plain"

    async def test_hover_other(self, monkeypatch) -> None:
        client = self._client(monkeypatch, {"result": {"contents": 42}})
        assert await client.hover("u", 0, 0) == "42"

    async def test_start(self, monkeypatch) -> None:
        client = LSPClient("python")
        client._initialized = True
        await client.start()

    async def test_document_symbols(self, monkeypatch) -> None:
        client = self._client(
            monkeypatch,
            {"result": [{"name": "f", "kind": 12, "detail": "d", "range": {"start": {"line": 0}}}, "skip"]},
        )
        out = await client.document_symbols("u")
        assert len(out) == 1
        assert out[0]["name"] == "f"

    async def test_document_symbols_error(self, monkeypatch) -> None:
        client = LSPClient("python")
        async def fail(method, params):
            raise RuntimeError("x")
        client._request = fail  # type: ignore[method-assign]
        assert await client.document_symbols("u") == []

    async def test_stop_kills_on_timeout(self, monkeypatch) -> None:
        client = LSPClient("python")
        proc = _fake_proc()
        proc.wait = AsyncMock(side_effect=[TimeoutError(), 0])
        client._process = proc
        await client.stop()
        proc.kill.assert_called_once()
        assert client._initialized is False

    async def test_stop_kill_process_lookup_error(self) -> None:
        client = LSPClient("python")
        proc = _fake_proc()
        proc.wait = AsyncMock(side_effect=[TimeoutError(), ProcessLookupError()])
        proc.kill = MagicMock()
        client._process = proc
        await client.stop()
        assert client._initialized is False


class TestPool:
    async def test_get_creates_and_caches(self) -> None:
        pool = LSPPool()
        c1 = await pool.get("python")
        c2 = await pool.get("python")
        assert c1 is c2

    async def test_get_value_error(self, monkeypatch) -> None:
        pool = LSPPool()
        monkeypatch.setattr(lsp_mod, "LSPClient", MagicMock(side_effect=ValueError()))
        assert await pool.get("python") is None

    async def test_diagnostics_no_client(self, monkeypatch) -> None:
        pool = LSPPool()
        async def none_get(language, root_uri=None):
            return None
        monkeypatch.setattr(pool, "get", none_get)
        assert await pool.diagnostics("a.py", "python") == []

    async def test_diagnostics_with_client(self, monkeypatch) -> None:
        pool = LSPPool()
        fake = MagicMock()
        fake.diagnostics = AsyncMock(return_value=[{"m": 1}])
        async def get(language, root_uri=None):
            return fake
        monkeypatch.setattr(pool, "get", get)
        assert await pool.diagnostics("a.py", "python") == [{"m": 1}]

    async def test_stop_all(self) -> None:
        pool = LSPPool()
        pool._clients["python"] = MagicMock()
        await pool.stop_all()
        assert pool._clients == {}

    async def test_stop_all_exception(self) -> None:
        pool = LSPPool()
        client = MagicMock()
        client.stop = AsyncMock(side_effect=RuntimeError("x"))
        pool._clients["python"] = client
        await pool.stop_all()
        assert pool._clients == {}

    def test_get_pool_singleton(self) -> None:
        assert get_lsp_pool() is get_lsp_pool()


class TestHelpers:
    def test_detect_language(self) -> None:
        assert _detect_language("a.py") == "python"
        assert _detect_language("a.tsx") == "typescript"
        assert _detect_language("a.unknown") == "python"

    def test_ext_to_lang(self) -> None:
        assert _ext_to_lang(".go") == "go"
        assert _ext_to_lang(".xyz") is None

    def test_scan_extensions(self, tmp_path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.ts").write_text("x", encoding="utf-8")
        (tmp_path / "noext").write_text("x", encoding="utf-8")
        exts = _scan_extensions(tmp_path)
        assert ".py" in exts and ".ts" in exts
        assert ".py" in exts

    def test_scan_extensions_permission_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(Path, "rglob", MagicMock(side_effect=PermissionError()))
        assert _scan_extensions(tmp_path) == []

    def test_find_key_files(self, tmp_path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.py").write_text("x", encoding="utf-8")
        files = _find_key_files(tmp_path, [".py"], max_files=1)
        assert len(files) == 1

    def test_find_key_files_permission_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(Path, "rglob", MagicMock(side_effect=PermissionError()))
        assert _find_key_files(tmp_path, [".py"], max_files=10) == []


class TestLspHelpers:
    async def test_completion_no_client(self, monkeypatch) -> None:
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=None))
        assert await lsp_completion("a.py", 0, 0) == ""

    async def test_completion_renders(self, monkeypatch) -> None:
        client = MagicMock()
        client.completion = AsyncMock(return_value=["a", "b"])
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        assert await lsp_completion("a.py", 0, 0) == "a\nb"

    async def test_definition_no_client(self, monkeypatch) -> None:
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=None))
        assert await lsp_definition("a.py", 0, 0) == ""

    async def test_definition_renders(self, monkeypatch) -> None:
        client = MagicMock()
        client.definition = AsyncMock(return_value=[{"uri": "file:///a.py", "line": 3}])
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        assert await lsp_definition("a.py", 0, 0) == "file:///a.py:3"

    async def test_references_no_client(self, monkeypatch) -> None:
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=None))
        assert await lsp_references("a.py", 0, 0) == ""

    async def test_references_renders(self, monkeypatch) -> None:
        client = MagicMock()
        client.references = AsyncMock(return_value=[{"uri": "u", "line": 1}])
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        assert await lsp_references("a.py", 0, 0) == "u:1"

    async def test_hover_no_client(self, monkeypatch) -> None:
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=None))
        assert await lsp_hover("a.py", 0, 0) == ""

    async def test_hover_renders(self, monkeypatch) -> None:
        client = MagicMock()
        client.hover = AsyncMock(return_value="docs")
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        assert await lsp_hover("a.py", 0, 0) == "docs"


class TestEnrichContext:
    async def test_root_not_found(self, tmp_path) -> None:
        assert await enrich_context(tmp_path / "nope") == "(project root not found)"

    async def test_no_source_files(self, tmp_path) -> None:
        (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
        assert await enrich_context(tmp_path) == "(no source files found in project)"

    async def test_no_lsp_available(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=None))
        result = await enrich_context(tmp_path)
        assert "server not available" in result

    async def test_with_diagnostics(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        client = MagicMock()
        client.diagnostics = AsyncMock(
            return_value=[
                {"range": {"start": {"line": 4}}, "message": "unused var", "severity": 1},
                {"range": {"start": {"line": 9}}, "message": "typo", "severity": 2},
            ]
        )
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        result = await enrich_context(tmp_path)
        assert "ERROR L4: unused var" in result
        assert "WARNING L9: typo" in result

    async def test_no_diagnostics_found(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        client = MagicMock()
        client.diagnostics = AsyncMock(return_value=[])
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        assert await enrich_context(tmp_path) == "(no LSP diagnostics found)"

    async def test_lang_without_files_skipped(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        client = MagicMock()
        monkeypatch.setattr(lsp_mod._lsp_pool, "get", AsyncMock(return_value=client))
        monkeypatch.setattr(lsp_mod, "_find_key_files", lambda root, exts, max_files: [])
        result = await enrich_context(tmp_path)
        assert "[python]" not in result
