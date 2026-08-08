from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from loguru import logger


def _cache_key(text: str) -> str:
    # md5 is fine for a content cache key (not security-sensitive)
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324


class EmbeddingEngine:
    def __init__(self, provider: str | None = None, model: str | None = None, cache_path: str | Path | None = None):
        from raven.core.config import get_settings

        self.provider = "local" if get_settings().ghost_mode else (provider or "local")
        self.model = model
        self._cache: dict[str, list[float]] = {}
        self._dirty = False
        self._cache_path = Path(cache_path) if cache_path else None
        if self._cache_path is None:
            try:
                from raven.core.config import settings

                self._cache_path = settings.resolved_data_dir / "cache" / "embeddings_cache.json"
            except Exception:
                self._cache_path = None
        self._load_disk_cache()

    def _load_disk_cache(self) -> None:
        path = self._cache_path
        if path is None or not path.exists():
            return
        try:
            with path.open() as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._cache = {k: list(v) for k, v in raw.items() if isinstance(v, list)}
                logger.debug("Loaded {} cached embeddings from {}", len(self._cache), path)
        except Exception as e:
            logger.warning("Failed to load embedding cache: {}", e)

    async def flush_cache(self) -> None:
        if not self._dirty or self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._write_cache)
            self._dirty = False
        except Exception as e:
            logger.warning("Failed to persist embedding cache: {}", e)

    def _write_cache(self) -> None:
        path = self._cache_path
        if path is None:
            return
        with path.open("w") as f:
            json.dump(self._cache, f)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        uncached: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            key = _cache_key(t)
            cached = self._cache.get(key)
            if cached is not None:
                results.append(cached)
            else:
                results.append([])
                uncached.append((i, t))
        if not uncached:
            return results
        uncached_texts = [t for _, t in uncached]
        if self.provider == "local":
            embeddings = await self._embed_local(uncached_texts)
        else:
            embeddings = await self._embed_openai(uncached_texts)
        for (idx, _), emb in zip(uncached, embeddings, strict=False):
            key = _cache_key(texts[idx])
            self._cache[key] = emb
            results[idx] = emb
        self._dirty = True
        await self.flush_cache()
        if len(self._cache) > 4096:
            evict = list(self._cache.keys())[:2048]
            for k in evict:
                self._cache.pop(k, None)
        return results

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        model = self.model or "text-embedding-3-small"
        api_key = self._get_openai_key()
        if not api_key:
            logger.warning("No OpenAI key, falling back to local embeddings")
            return await self._embed_local(texts)
        try:
            import httpx

            chunk_size = 100
            all_results: list[list[float]] = []
            async with httpx.AsyncClient(timeout=60) as c:
                for i in range(0, len(texts), chunk_size):
                    chunk = texts[i : i + chunk_size]
                    resp = await c.post(
                        "https://api.openai.com/v1/embeddings",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"input": chunk, "model": model},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        all_results.extend(d["embedding"] for d in data["data"])
                    else:
                        logger.error("OpenAI embedding error: {} {}", resp.status_code, resp.text)
                        return await self._embed_local(texts)
            return all_results
        except Exception as e:
            logger.error("OpenAI embedding failed: {}", e)
            return await self._embed_local(texts)

    async def _embed_local(self, texts: list[str]) -> list[list[float]]:
        try:
            from sentence_transformers import SentenceTransformer

            model_name = self.model or "all-MiniLM-L6-v2"
            model = SentenceTransformer(model_name)
            embeddings = model.encode(texts, show_progress_bar=False)
            result: list[list[float]] = embeddings.tolist()
            return result
        except ImportError:
            raise RuntimeError("sentence-transformers not installed — cannot embed locally") from None
        except Exception as e:
            logger.error("Local embedding failed: {}", e)
            raise

    @staticmethod
    def _get_openai_key() -> str:
        try:
            from raven.core.config import settings

            return settings.openai_api_key.get_secret_value() or ""
        except Exception as exc:
            logger.debug("Falling back to env OPENAI_API_KEY: {}", exc)
            import os

            return os.environ.get("OPENAI_API_KEY", "")

    def clear_cache(self):
        self._cache.clear()
        self._dirty = False
