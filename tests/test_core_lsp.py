from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestLSPClient:
    def setup_method(self) -> None:
        self.patcher = patch("raven.core.lsp.LSPClient.start", new_callable=AsyncMock)
        self.mock_start = self.patcher.start()

    def teardown_method(self) -> None:
        self.patcher.stop()

    def test_detect_lang_python(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("foo.py") == "python"
        assert _detect_lang("foo.pyi") == "python"

    def test_detect_lang_typescript(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("foo.ts") == "typescript"
        assert _detect_lang("foo.tsx") == "typescript"

    def test_detect_lang_javascript(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("foo.js") == "javascript"
        assert _detect_lang("foo.jsx") == "javascript"

    def test_detect_lang_go(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("main.go") == "go"

    def test_detect_lang_rust(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("main.rs") == "rust"

    def test_detect_lang_unknown_defaults_to_python(self) -> None:
        from raven.core.lsp import _detect_lang

        assert _detect_lang("foo.xyz") == "python"

    def test_scan_extensions_empty_dir(self, tmp_path: pytest.TempPathFactory) -> None:
        from raven.core.lsp import _scan_extensions

        exts = _scan_extensions(tmp_path)
        assert exts == []

    def test_scan_extensions_with_files(self, tmp_path: pytest.TempPathFactory) -> None:
        from raven.core.lsp import _scan_extensions

        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.ts").write_text("")
        (tmp_path / "c.go").write_text("")
        exts = _scan_extensions(tmp_path)
        assert ".py" in exts
        assert ".ts" in exts
        assert ".go" in exts

    @pytest.mark.asyncio
    async def test_lsp_completion_error_returns_error_string(self) -> None:
        from raven.core.lsp import lsp_completion

        result = await lsp_completion("/nonexistent/file.py", 0, 0)
        assert result.startswith("[error]")

    @pytest.mark.asyncio
    async def test_lsp_hover_error_returns_error_string(self) -> None:
        from raven.core.lsp import lsp_hover

        result = await lsp_hover("/nonexistent/file.py", 0, 0)
        assert result.startswith("[error]")

    @pytest.mark.asyncio
    async def test_lsp_definition_error_returns_error_string(self) -> None:
        from raven.core.lsp import lsp_definition

        result = await lsp_definition("/nonexistent/file.py", 0, 0)
        assert result.startswith("[error]")

    @pytest.mark.asyncio
    async def test_lsp_references_error_returns_error_string(self) -> None:
        from raven.core.lsp import lsp_references

        result = await lsp_references("/nonexistent/file.py", 0, 0)
        assert result.startswith("[error]")


class TestLSPClientConstructor:
    def test_lsp_client_language_map(self) -> None:
        from raven.core.lsp import LSPClient

        client = LSPClient("python")
        assert client.language == "python"

    @pytest.mark.asyncio
    async def test_lsp_client_unsupported_language(self) -> None:
        from raven.core.lsp import LSPClient

        client = LSPClient("ruby")
        with pytest.raises(ValueError, match="LSP server not found for language"):
            await client.start()


class TestLSPClientStop:
    @pytest.mark.asyncio
    async def test_stop_without_start_does_not_crash(self) -> None:
        from raven.core.lsp import LSPClient

        client = LSPClient("python")
        await client.stop()
