from __future__ import annotations

import numpy as np
from loguru import logger


class EmbeddingEngine:
    def __init__(self, provider: str = "openai", model: str | None = None):
        self.provider = provider
        self.model = model
        self._local_model = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "openai":
            return await self._embed_openai(texts)
        elif self.provider == "local":
            return await self._embed_local(texts)
        else:
            return await self._embed_openai(texts)

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        model = self.model or "text-embedding-3-small"
        api_key = self._get_openai_key()
        if not api_key:
            logger.warning("No OpenAI key, falling back to local embeddings")
            return await self._embed_local(texts)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as c:
                resp = await c.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"input": texts, "model": model},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return [d["embedding"] for d in data["data"]]
                else:
                    logger.error("OpenAI embedding error: {} {}", resp.status_code, resp.text)
                    return await self._embed_local(texts)
        except Exception as e:
            logger.error("OpenAI embedding failed: {}", e)
            return await self._embed_local(texts)

    async def _embed_local(self, texts: list[str]) -> list[list[float]]:
        try:
            if self._local_model is None:
                from sentence_transformers import SentenceTransformer
                model_name = self.model or "all-MiniLM-L6-v2"
                self._local_model = SentenceTransformer(model_name)
            emb = self._local_model.encode(texts, show_progress_bar=False)
            return emb.tolist()
        except ImportError:
            return [np.random.rand(384).tolist() for _ in texts]
        except Exception as e:
            logger.error("Local embedding failed: {}", e)
            return [np.random.rand(384).tolist() for _ in texts]

    @staticmethod
    def _get_openai_key() -> str:
        try:
            from raven.core.config import settings
            return settings.openai_api_key or ""
        except Exception:
            import os
            return os.environ.get("OPENAI_API_KEY", "")
