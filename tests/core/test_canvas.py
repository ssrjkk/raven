from __future__ import annotations

import pytest

from raven.tools.canvas import _sanitize, _sanitize_url, canvas_render


class TestCanvas:
    async def test_render_text(self):
        result = canvas_render([{"type": "text", "content": "hello"}])
        assert result == "hello"

    async def test_render_code(self):
        result = canvas_render([{"type": "code", "language": "py", "content": "x = 1"}])
        assert "```py" in result
        assert "x = 1" in result

    async def test_render_table(self):
        result = canvas_render([{"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]}])
        assert "A | B" in result
        assert "1 | 2" in result

    async def test_render_mermaid(self):
        result = canvas_render([{"type": "mermaid", "content": "graph TD; A-->B"}])
        assert "```mermaid" in result

    async def test_render_link(self):
        result = canvas_render([{"type": "link", "content": "click", "url": "https://example.com"}])
        assert "[click](https://example.com)" in result

    async def test_render_image(self):
        result = canvas_render([{"type": "image", "content": "alt", "url": "https://example.com/img.png"}])
        assert "![alt](https://example.com/img.png)" in result

    async def test_render_list(self):
        result = canvas_render([{"type": "list", "items": ["a", "b"]}])
        assert "- a" in result
        assert "- b" in result

    async def test_render_alert(self):
        result = canvas_render([{"type": "alert", "content": "danger", "level": "danger"}])
        assert "[!DANGER]" in result
        assert "danger" in result

    async def test_xss_sanitize_text(self):
        result = canvas_render([{"type": "text", "content": "<script>alert(1)</script>"}])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    async def test_xss_sanitize_link_url(self):
        result = canvas_render([{"type": "link", "content": "xss", "url": "javascript:alert(1)"}])
        assert "javascript:" not in result

    async def test_xss_sanitize_image_url(self):
        result = canvas_render([{"type": "image", "content": "xss", "url": "javascript:alert(1)"}])
        assert "javascript:" not in result

    async def test_xss_sanitize_table_content(self):
        result = canvas_render([{"type": "table", "headers": ["<script>"], "rows": [["<img>", "safe"]]}])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
        assert "&lt;img&gt;" in result

    async def test_xss_sanitize_list(self):
        result = canvas_render([{"type": "list", "items": ["<b>bold</b>"]}])
        assert "<b>" not in result
        assert "&lt;b&gt;" in result

    async def test_xss_sanitize_alert(self):
        result = canvas_render([{"type": "alert", "content": "<script>hack()</script>", "level": "info"}])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    async def test_render_unknown_type(self):
        result = canvas_render([{"type": "nonexistent", "content": "raw"}])
        assert result == "raw"

    async def test_render_multiple_components(self):
        result = canvas_render([
            {"type": "text", "content": "hello"},
            {"type": "code", "language": "py", "content": "pass"},
        ])
        assert "hello" in result
        assert "```py" in result


class TestSanitize:
    def test_sanitize_escapes_html(self):
        assert _sanitize("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_sanitize_url_allowed(self):
        assert _sanitize_url("https://example.com") == "https://example.com"

    def test_sanitize_url_blocked(self):
        assert _sanitize_url("javascript:alert(1)") == ""

    def test_sanitize_url_relative(self):
        assert _sanitize_url("/path/to/file") == "/path/to/file"

    def test_sanitize_url_mailto(self):
        assert _sanitize_url("mailto:test@test.com") == "mailto:test@test.com"
