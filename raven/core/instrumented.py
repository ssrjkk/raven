from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.metrics import metrics


class InstrumentedLLMProvider(LLMProvider):
    def __init__(self, provider: LLMProvider, provider_name: str):
        self._wrapped = provider
        self._provider_name = provider_name

    async def complete(
        self, messages: list[dict[str, object]], model: str, tools: list[dict[str, object]] | None = None
    ) -> LLMResponse:
        start = asyncio.get_running_loop().time()
        try:
            result = await self._wrapped.complete(messages, model, tools)
            metrics.inc("llm_complete", {"provider": self._provider_name, "model": model, "status": "ok"})
            return result
        except Exception:
            metrics.inc("llm_complete", {"provider": self._provider_name, "model": model, "status": "error"})
            raise
        finally:
            dur = asyncio.get_running_loop().time() - start
            metrics.observe("llm_request", dur, {"provider": self._provider_name, "model": model})

    async def complete_stream(
        self, messages: list[dict[str, object]], model: str, tools: list[dict[str, object]] | None = None
    ) -> AsyncIterator[str]:
        start = asyncio.get_running_loop().time()
        try:
            async for token in self._wrapped.complete_stream(messages, model, tools):
                yield token
            metrics.inc("llm_stream", {"provider": self._provider_name, "model": model, "status": "ok"})
        except Exception:
            metrics.inc("llm_stream", {"provider": self._provider_name, "model": model, "status": "error"})
            raise
        finally:
            dur = asyncio.get_running_loop().time() - start
            metrics.observe("llm_request", dur, {"provider": self._provider_name, "model": model})

    async def cleanup(self):
        await self._wrapped.cleanup()
