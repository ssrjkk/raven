from __future__ import annotations

from typing import Any

from ravencode.runtime.plugins import Plugin


async def http_get(url: str, headers: dict[str, str] | None = None) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers or {})
            resp.raise_for_status()
        content = resp.text[:50_000]
        return f"[200 OK] {len(content)} chars\n{content}"
    except ImportError:
        return "[error] httpx not installed"
    except Exception as exc:
        return f"[error] {exc}"


async def http_post(url: str, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(url, json=data, headers=headers or {})
            resp.raise_for_status()
        content = resp.text[:50_000]
        return f"[{resp.status_code}] {len(content)} chars\n{content}"
    except ImportError:
        return "[error] httpx not installed"
    except Exception as exc:
        return f"[error] {exc}"


def register() -> Plugin:
    tools = {
        "http_get": {
            "name": "http_get",
            "dangerous": False,
            "description": "Make an HTTP GET request to an arbitrary URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL"},
                    "headers": {"type": "object", "description": "Optional HTTP headers", "default": None},
                },
                "required": ["url"],
            },
            "handler": http_get,
        },
        "http_post": {
            "name": "http_post",
            "dangerous": True,
            "description": "Make an HTTP POST request with JSON body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL"},
                    "data": {"type": "object", "description": "JSON body", "default": None},
                    "headers": {"type": "object", "description": "Optional HTTP headers", "default": None},
                },
                "required": ["url"],
            },
            "handler": http_post,
        },
    }
    return Plugin(name="example-http", version="0.1.0", tools=tools)
