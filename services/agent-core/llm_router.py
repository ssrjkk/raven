from __future__ import annotations

import os
import time

import httpx
from loguru import logger

from services.observability_sdk.circuit_breaker import CircuitBreaker
from services.observability_sdk.retry import DEFAULT_RETRY


class LLMRouter:
    def __init__(self):
        self._api_key = os.environ.get("LLM_API_KEY", "")
        self._base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        self._model = os.environ.get("LLM_MODEL", "gpt-4")
        self._client = httpx.AsyncClient(timeout=120.0)
        self._cb = CircuitBreaker("llm", failure_threshold=3, recovery_timeout=30.0)
        self._metrics = {"total_calls": 0, "failed_calls": 0, "total_tokens": 0}
        logger.info("LLM router initialized: model={}, base_url={}", self._model, self._base_url)

    async def chat(self, messages: list[dict], session_id: str | None = None) -> dict:
        return await self._cb.call(self._do_chat, messages, session_id)

    async def _do_chat(self, messages: list[dict], session_id: str | None = None) -> dict:
        start = time.monotonic()
        self._metrics["total_calls"] += 1

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "messages": messages, "user": session_id},
            )
            response.raise_for_status()
            data = response.json()

            usage = data.get("usage", {})
            self._metrics["total_tokens"] += usage.get("total_tokens", 0)
            elapsed = time.monotonic() - start
            logger.info("LLM call completed in {:.1f}s, tokens={}", elapsed, usage.get("total_tokens", 0))

            return {
                "response": data["choices"][0]["message"]["content"],
                "model": self._model,
                "tokens_used": usage.get("total_tokens", 0),
                "duration_ms": round(elapsed * 1000),
            }
        except httpx.HTTPStatusError as e:
            self._metrics["failed_calls"] += 1
            logger.error("LLM API error: {} {} {}", e.response.status_code, e.response.text[:200])
            raise
        except Exception as e:
            self._metrics["failed_calls"] += 1
            logger.error("LLM call failed: {}", e)
            raise

    async def stream(self, messages: list[dict]) -> httpx.Response:
        return await DEFAULT_RETRY.execute(
            self._client.post,
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "messages": messages, "stream": True},
            operation_name="llm_stream",
        )

    async def close(self):
        await self._client.aclose()
