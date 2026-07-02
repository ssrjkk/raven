from __future__ import annotations

from collections.abc import AsyncIterator
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


class AIUnavailableError(RuntimeError):
    """Raised when the AI backend cannot be reached."""


class AIOSClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or f"http://localhost:{settings.web_port}"
        self._llm: LLMRouter | None = None

    def _get_llm(self) -> LLMRouter | None:
        if self._llm is None:
            try:
                from raven.core.llm import LLMRouter
                from ravencode.config.loader import get_config
                cfg = get_config()
                providers_config: dict[str, Any] = {}
                for p in cfg.resolve_providers():
                    overrides: dict[str, str] = {}
                    if p.api_key:
                        overrides["api_key"] = p.api_key
                    if p.base_url:
                        overrides["base_url"] = p.base_url
                    if p.options:
                        overrides.update(p.options)
                    if overrides:
                        providers_config[p.id] = overrides
                self._llm = LLMRouter(providers_config=providers_config)
            except Exception as exc:
                logger.warning("LLMRouter unavailable: {}", exc)
                self._llm = None
        return self._llm

    def _pick_provider(self, task: str) -> str:
        return _PROVIDER_ROUTING.get(task, "openrouter")

    def _require_llm(self) -> LLMRouter:
        llm = self._get_llm()
        if llm is None:
            raise AIUnavailableError("AI backend unavailable. Configure API keys in .env and restart.")
        return llm

    async def ask(
        self,
        prompt: str,
        task: str = "code",
        model: str | None = None,
    ) -> AIResponse:
        try:
            return await self.ask_messages(
                messages=[{"role": "user", "content": prompt}],
                task=task,
                model=model,
            )
        except AIUnavailableError as exc:
            return AIResponse(text=str(exc), model=model or "none", provider="none")
        except Exception as exc:
            logger.error("AI request failed: {}", exc)
            return AIResponse(text=f"Request failed: {exc}", model=model or "none", provider="none")

    async def ask_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        task: str = "code",
        model: str | None = None,
    ) -> AIResponse:
        llm = self._require_llm()
        provider = self._pick_provider(task)
        model_name = model or settings.default_model
        response = await llm.complete(messages=messages, tools=tools, model=model_name)
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

    async def ask_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        llm = self._require_llm()
        model_name = model or settings.default_model
        async for token in llm.complete_stream(messages=messages, tools=tools, model=model_name):
            yield token


async def ask_stream(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    client = AIOSClient()
    async for token in client.ask_stream(messages=messages, tools=tools, model=model):
        yield token
