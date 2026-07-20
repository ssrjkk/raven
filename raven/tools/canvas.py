from __future__ import annotations

import asyncio
import html
from typing import Any

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "/"})
_ALLOWED_ALERT_LEVELS = frozenset({"info", "warning", "danger", "success"})


def _sanitize(text: str) -> str:
    return html.escape(text, quote=True)


def _sanitize_url(url: str) -> str:
    url = url.strip()
    if any(url.startswith(s) for s in _SAFE_URL_SCHEMES):
        return html.escape(url, quote=True)
    return ""


def canvas_render(components: list[dict[str, Any]]) -> str:
    rendered = []
    for comp in components:
        ctype = comp.get("type", "text")
        content = comp.get("content", "")
        if ctype == "text":
            rendered.append(_sanitize(content))
        elif ctype == "code":
            lang = _sanitize(comp.get("language", ""))
            rendered.append(f"```{lang}\n{content}\n```")
        elif ctype == "table":
            headers = [_sanitize(h) for h in comp.get("headers", [])]
            rows = [[_sanitize(str(c)) for c in row] for row in comp.get("rows", [])]
            header = " | ".join(headers)
            sep = " | ".join(["---"] * len(headers))
            body = "\n".join(" | ".join(row) for row in rows)
            rendered.append(f"{header}\n{sep}\n{body}")
        elif ctype == "mermaid":
            rendered.append(f"```mermaid\n{content}\n```")
        elif ctype == "link":
            url = comp.get("url", "")
            rendered.append(f"[{_sanitize(content)}]({_sanitize_url(url)})")
        elif ctype == "image":
            url = comp.get("url", "")
            rendered.append(f"![{_sanitize(content)}]({_sanitize_url(url)})")
        elif ctype == "list":
            items = [_sanitize(i) for i in comp.get("items", [])]
            rendered.append("\n".join(f"- {i}" for i in items))
        elif ctype == "alert":
            level = comp.get("level", "info")
            level = level.lower() if level.lower() in _ALLOWED_ALERT_LEVELS else "info"
            rendered.append(f"> [!{level.upper()}]\n> {_sanitize(content)}")
        else:
            rendered.append(_sanitize(content))
    return "\n\n".join(rendered)


async def canvas_show(path: str, width: int = 800, height: int = 600) -> str:
    try:
        import tempfile
        import webbrowser
        from pathlib import Path
        content = await asyncio.to_thread(lambda: Path(path).read_text(encoding="utf-8"))
        tmp_dir = await asyncio.to_thread(tempfile.mkdtemp)
        tmp = Path(tmp_dir) / "canvas.html"
        await asyncio.to_thread(lambda: tmp.write_text(content, encoding="utf-8"))
        await asyncio.to_thread(webbrowser.open, tmp.as_uri())
        return f"Canvas opened in browser: {tmp}"
    except Exception as exc:
        return f"[error] canvas_show: {exc}"


async def canvas_save(content: str, path: str, fmt: str = "md") -> str:
    from pathlib import Path
    try:
        p = Path(path)
        await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
        if fmt == "html":
            text = f"<!DOCTYPE html><html><body>{content}</body></html>"
            await asyncio.to_thread(lambda: p.write_text(text, encoding="utf-8"))
        else:
            await asyncio.to_thread(lambda: p.write_text(content, encoding="utf-8"))
        return f"Canvas saved to {p} ({len(content)} bytes)"
    except Exception as exc:
        return f"[error] canvas_save: {exc}"


def register_canvas_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="canvas_render",
        description="Render visual components (text, code, table, mermaid, link, image, list, alert) into formatted output",
        parameters={
            "components": {
                "type": "array",
                "description": "List of component dicts with type, content, and optional fields",
                "required": True,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "text|code|table|mermaid|link|image|list|alert"},
                        "content": {"type": "string", "description": "Component content"},
                        "language": {"type": "string", "description": "Language for code blocks"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array"}},
                        "url": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                        "level": {"type": "string", "description": "info|warning|danger|success"},
                    },
                },
            }
        },
        handler=canvas_render,
        category="visual",
    ))
    registry.register(ToolSpec(
        name="canvas_show",
        description="Open an HTML file as a visual canvas in the browser",
        parameters={
            "path": {"type": "string", "description": "Path to HTML file", "required": True},
            "width": {"type": "integer", "description": "Canvas width", "required": False},
            "height": {"type": "integer", "description": "Canvas height", "required": False},
        },
        handler=canvas_show,
        category="visual",
    ))
    registry.register(ToolSpec(
        name="canvas_save",
        description="Save rendered content to a file (md or html)",
        parameters={
            "content": {"type": "string", "description": "Content to save", "required": True},
            "path": {"type": "string", "description": "File path", "required": True},
            "fmt": {"type": "string", "description": "Format: md or html", "required": False},
        },
        handler=canvas_save,
        category="visual",
    ))
