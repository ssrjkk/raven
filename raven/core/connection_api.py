"""REST API for Connection Management.

Provides CRUD endpoints for:
  * LLM providers (with a live connection test)
  * Contexts (scoped to repos/files/folders, optionally bound to a provider)
  * Agents (bound to a provider + context, with run history)

All data persists to ``data/connections.json`` (plain JSON, API keys are
written verbatim — operators are expected to control access to the data dir).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from raven.core._json import json

_T = TypeVar("_T")

CONNECTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "connections.json"

PROVIDER_TYPES = (
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "vllm",
    "groq",
    "azure",
    "vertex",
    "bedrock",
    "copilot",
)

_PROVIDER_MODEL_HINTS: dict[str, str] = {
    "openai": "openai/gpt-4o-mini",
    "anthropic": "anthropic/claude-3-5-sonnet-latest",
    "openrouter": "openrouter/openai/o3-mini",
    "ollama": "ollama/llama3",
    "vllm": "vllm/llama3",
    "groq": "groq/llama3-70b-8192",
}


# --------------------------------------------------------------------------- #
# Thread-safe store
# --------------------------------------------------------------------------- #
class _Store:
    def __init__(self, path: Path = CONNECTIONS_FILE) -> None:
        self._path = path
        self._data: dict[str, Any] = {"providers": [], "contexts": [], "agents": []}
        self._lock = asyncio.Lock()

    def load(self) -> dict[str, Any]:
        if self._path.exists():
            raw = self._path.read_text(encoding="utf-8")
            if raw.strip():
                try:
                    loaded = json.loads(raw)
                    for key in ("providers", "contexts", "agents"):
                        if isinstance(loaded.get(key), list):
                            self._data[key] = loaded[key]
                except json.JSONDecodeError:
                    logger.warning("[connections] store corrupted, using defaults")
        return self._data

    def _save_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def mutate(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Run *fn()* under the write lock, then persist."""
        async with self._lock:
            result = fn()
            self._save_sync()
            return result


_store = _Store()
_store.load()


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class ProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = "openrouter"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    enabled: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class UpdateProviderPayload(BaseModel):
    """Partial update — every field is optional (PATCH semantics via PUT)."""
    name: str | None = None
    type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    enabled: bool | None = None
    extra: dict[str, Any] | None = None


class ProviderTestRequest(BaseModel):
    type: str = "openrouter"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class ContextPayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    provider: str = ""
    repositories: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)
    filters: str = ""
    description: str = ""


class AgentPayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    provider: str = ""
    context: str = ""
    model: str = ""
    system_prompt: str = ""
    enabled: bool = True


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * min(len(key), 8) if key else ""
    return f"{key[:4]}...{key[-4:]}"


def _is_masked(key: str) -> bool:
    """Return True if *key* looks like a masked value from ``_mask_key``."""
    return "..." in key or (len(key) == 8 and key == "*" * 8)


def _public_provider(p: dict[str, Any]) -> dict[str, Any]:
    out = dict(p)
    out["api_key"] = _mask_key(p.get("api_key", ""))
    return out


def _validate_base_url_scheme(url: str) -> None:
    """Reject non-HTTP(S) schemes in user-supplied URLs (SSRF-lite guard)."""
    if not url:
        return
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(400, f"Unsupported URL scheme: {parsed.scheme!r}. Only http/https allowed.")


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def create_connection_router(dependencies: list[Any] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/connections", tags=["connections"], dependencies=dependencies or [])

    # ----- Providers -----
    @router.get("/providers")
    async def list_providers() -> dict[str, Any]:
        async with _store._lock:
            providers = [_public_provider(p) for p in _store._data["providers"]]
        return {"providers": providers}

    @router.get("/providers/{name}")
    async def get_provider(name: str) -> dict[str, Any]:
        async with _store._lock:
            for p in _store._data["providers"]:
                if p.get("name") == name:
                    return _public_provider(p)
        raise HTTPException(404, f"Provider '{name}' not found")

    @router.post("/providers")
    async def create_provider(body: ProviderPayload) -> dict[str, Any]:
        _validate_base_url_scheme(body.base_url)

        def _do() -> dict[str, Any]:
            providers = _store._data["providers"]
            if any(p.get("name") == body.name for p in providers):
                raise HTTPException(409, f"Provider '{body.name}' already exists")
            if body.type not in PROVIDER_TYPES:
                raise HTTPException(400, f"Unknown provider type '{body.type}'")
            record = body.model_dump()
            record["created_at"] = time.time()
            record["updated_at"] = time.time()
            providers.append(record)
            return _public_provider(record)

        result = await _store.mutate(_do)
        logger.info("[connections] provider created: {} ({})", body.name, body.type)
        return result

    @router.put("/providers/{name}")
    async def update_provider(name: str, body: UpdateProviderPayload) -> dict[str, Any]:
        _validate_base_url_scheme(body.base_url or "")

        def _do() -> dict[str, Any]:
            providers = _store._data["providers"]
            for i, p in enumerate(providers):
                if p.get("name") == name:
                    # Merge partial fields into existing record
                    updated = dict(p)
                    if body.name is not None:
                        updated["name"] = body.name
                    if body.type is not None:
                        updated["type"] = body.type
                    if body.api_key is not None:
                        # Preserve real key when a masked value is sent
                        if _is_masked(body.api_key):
                            pass  # keep existing key
                        else:
                            updated["api_key"] = body.api_key
                    if body.base_url is not None:
                        updated["base_url"] = body.base_url
                    if body.model is not None:
                        updated["model"] = body.model
                    if body.enabled is not None:
                        updated["enabled"] = body.enabled
                    if body.extra is not None:
                        updated["extra"] = body.extra
                    updated["updated_at"] = time.time()
                    providers[i] = updated
                    return _public_provider(updated)
            raise HTTPException(404, f"Provider '{name}' not found")

        result = await _store.mutate(_do)
        logger.info("[connections] provider updated: {}", name)
        return result

    @router.delete("/providers/{name}")
    async def delete_provider(name: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            providers = _store._data["providers"]
            for i, p in enumerate(providers):
                if p.get("name") == name:
                    providers.pop(i)
                    # Cascade: delete contexts bound to this provider
                    ctx_ids_to_delete = {c["id"] for c in _store._data["contexts"] if c.get("provider") == name}
                    _store._data["contexts"] = [
                        c for c in _store._data["contexts"] if c.get("provider") != name
                    ]
                    # Cascade: unlink agents (clear provider, clear context if its ctx was deleted)
                    for ag in _store._data["agents"]:
                        if ag.get("provider") == name:
                            ag["provider"] = ""
                        if ag.get("context") in ctx_ids_to_delete:
                            ag["context"] = ""
                    return {"ok": True}
            raise HTTPException(404, f"Provider '{name}' not found")

        result = await _store.mutate(_do)
        logger.info("[connections] provider deleted: {}", name)
        return result

    @router.post("/providers/test")
    async def test_provider(body: ProviderTestRequest) -> dict[str, Any]:
        if body.type not in PROVIDER_TYPES:
            raise HTTPException(400, f"Unknown provider type '{body.type}'")
        _validate_base_url_scheme(body.base_url)
        model = body.model
        if not model and body.type in _PROVIDER_MODEL_HINTS:
            model = _PROVIDER_MODEL_HINTS[body.type]
        if not model:
            raise HTTPException(400, "A model is required to test the provider")
        from pydantic import SecretStr

        from raven.core.llm.factory import LLMProviderFactory

        provider = LLMProviderFactory.create(
            body.type,
            api_key=SecretStr(body.api_key),
            base_url=body.base_url,
            timeout=15,
        )
        try:
            resp = await asyncio.wait_for(
                provider.complete([{"role": "user", "content": "ping"}], model),
                timeout=30,
            )
            return {"ok": True, "model": model, "reply": (resp.content or "")[:120]}
        except Exception as exc:
            raise HTTPException(502, f"Connection failed: {exc}") from exc
        finally:
            await provider.cleanup()

    # ----- Contexts -----
    @router.get("/contexts")
    async def list_contexts() -> dict[str, Any]:
        async with _store._lock:
            return {"contexts": list(_store._data["contexts"])}

    @router.post("/contexts")
    async def create_context(body: ContextPayload) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            ctx = body.model_dump()
            ctx["id"] = body.id or f"ctx-{uuid.uuid4().hex[:12]}"
            ctx["created_at"] = time.time()
            ctx["updated_at"] = time.time()
            _store._data["contexts"].append(ctx)
            return ctx

        result = await _store.mutate(_do)
        logger.info("[connections] context created: {} ({})", result["name"], result["id"])
        return result

    @router.put("/contexts/{ctx_id}")
    async def update_context(ctx_id: str, body: ContextPayload) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            contexts = _store._data["contexts"]
            for i, c in enumerate(contexts):
                if c.get("id") == ctx_id:
                    updated = body.model_dump()
                    updated["id"] = ctx_id
                    updated["created_at"] = c.get("created_at", time.time())
                    updated["updated_at"] = time.time()
                    contexts[i] = updated
                    return updated
            raise HTTPException(404, f"Context '{ctx_id}' not found")

        return await _store.mutate(_do)

    @router.delete("/contexts/{ctx_id}")
    async def delete_context(ctx_id: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            contexts = _store._data["contexts"]
            for i, c in enumerate(contexts):
                if c.get("id") == ctx_id:
                    contexts.pop(i)
                    # Cascade: unlink agents pointing at this context
                    for a in _store._data["agents"]:
                        if a.get("context") == ctx_id:
                            a["context"] = ""
                    return {"ok": True}
            raise HTTPException(404, f"Context '{ctx_id}' not found")

        return await _store.mutate(_do)

    # ----- Agents -----
    @router.get("/agents")
    async def list_agents() -> dict[str, Any]:
        async with _store._lock:
            return {"agents": list(_store._data["agents"])}

    @router.post("/agents")
    async def create_agent(body: AgentPayload) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            agent = body.model_dump()
            agent["id"] = body.id or f"ag-{uuid.uuid4().hex[:12]}"
            agent["history"] = []
            agent["created_at"] = time.time()
            agent["updated_at"] = time.time()
            _store._data["agents"].append(agent)
            return agent

        result = await _store.mutate(_do)
        logger.info("[connections] agent created: {} ({})", result["name"], result["id"])
        return result

    @router.put("/agents/{agent_id}")
    async def update_agent(agent_id: str, body: AgentPayload) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            agents = _store._data["agents"]
            for i, a in enumerate(agents):
                if a.get("id") == agent_id:
                    updated = body.model_dump()
                    updated["id"] = agent_id
                    updated["history"] = a.get("history", [])
                    updated["created_at"] = a.get("created_at", time.time())
                    updated["updated_at"] = time.time()
                    agents[i] = updated
                    return updated
            raise HTTPException(404, f"Agent '{agent_id}' not found")

        return await _store.mutate(_do)

    @router.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            agents = _store._data["agents"]
            for i, a in enumerate(agents):
                if a.get("id") == agent_id:
                    agents.pop(i)
                    return {"ok": True}
            raise HTTPException(404, f"Agent '{agent_id}' not found")

        return await _store.mutate(_do)

    @router.post("/agents/{agent_id}/log")
    async def append_agent_log(
        agent_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Append an entry to an agent's run history."""
        def _do() -> dict[str, Any]:
            for a in _store._data["agents"]:
                if a.get("id") == agent_id:
                    entry = {
                        "ts": time.time(),
                        "role": body.get("role", "user"),
                        "content": body.get("content", ""),
                    }
                    a.setdefault("history", []).append(entry)
                    a["history"] = a["history"][-200:]  # cap
                    a["updated_at"] = time.time()
                    return {"ok": True}
            raise HTTPException(404, f"Agent '{agent_id}' not found")

        return await _store.mutate(_do)

    return router
