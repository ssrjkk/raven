"""High-level AI client — streaming, multi-provider, tool support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.config import settings

if TYPE_CHECKING:
    from raven.core.llm import LLMRouter


@dataclass
class AIResponse:
    text: str
    model: str
    provider: str
    usage: dict[str, int] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


_PROVIDER_ROUTING = {
    "architecture": "anthropic",
    "fast": "openai",
    "code": "openrouter",
    "debug": "openrouter",
    "refactor": "anthropic",
    "plan": "openrouter",
    "explain": "anthropic",
    "search": "openai",
}


class AIOSClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or f"http://localhost:{settings.web_port}"
        self._llm: LLMRouter | None = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from raven.core.llm import LLMRouter
                self._llm = LLMRouter()
            except Exception as exc:
                logger.warning("LLMRouter unavailable (API keys missing?): {}", exc)
                self._llm = None
        return self._llm

    def _pick_provider(self, task: str) -> str:
        return _PROVIDER_ROUTING.get(task, "openrouter")

    async def ask(
        self,
        prompt: str,
        task: str = "code",
        model: str | None = None,
    ) -> AIResponse:
        llm = self._get_llm()
        if llm is None:
            return AIResponse(
                text="AI backend unavailable. Configure API keys in .env and restart.",
                model=model or "none",
                provider="none",
            )
        provider = self._pick_provider(task)
        model_name = model or settings.default_model
        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=model_name,
            )
            content = response.content if hasattr(response, "content") else str(response)
            tool_calls_raw = getattr(response, "tool_calls", [])
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in (tool_calls_raw or [])
            ]
            return AIResponse(
                text=content,
                model=model_name,
                provider=provider,
                tool_calls=tool_calls,
            )
        except Exception as exc:
            logger.error("AI request failed: {}", exc)
            return AIResponse(text=f"Request failed: {exc}", model=model_name, provider=provider)

    async def ask_stream(
        self,
        prompt: str,
        task: str = "code",
        model: str | None = None,
    ):
        """Stream tokens from the LLM. Yields strings."""
        llm = self._get_llm()
        if llm is None:
            yield "AI backend unavailable. Configure API keys in .env and restart."
            return
        model_name = model or settings.default_model
        try:
            async for token in llm.complete_stream(
                messages=[{"role": "user", "content": prompt}],
                model=model_name,
            ):
                yield token
        except Exception as exc:
            logger.error("AI stream failed: {}", exc)
            yield f"\n[error: {exc}]"
