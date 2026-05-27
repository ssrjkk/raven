"""High-level AI client wrapping Raven's gateway and LLM router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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

        provider_map = {
            "architecture": "anthropic",
            "fast": "openai",
            "code": "openrouter",
            "debug": "openrouter",
            "refactor": "anthropic",
        }

        provider = provider_map.get(task, "openrouter")
        model_name = model or settings.default_model

        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=model_name,
                provider=provider,
            )
            content = response.content if hasattr(response, "content") else str(response)

            return AIResponse(text=content, model=model_name, provider=provider)
        except Exception as exc:
            logger.error("AI request failed: {}", exc)
            return AIResponse(text=f"Request failed: {exc}", model=model_name, provider=provider)
