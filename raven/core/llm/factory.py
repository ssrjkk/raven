from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from raven.core.llm.protocol import LLMProvider
from raven.core.llm.providers import (
    AnthropicProvider,
    AzureProvider,
    BedrockProvider,
    CopilotProvider,
    GroqProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
    VertexAIProvider,
    VLLMProvider,
)


class LLMProviderFactory:
    @staticmethod
    def create(provider: str, api_key: SecretStr | None = None, **kwargs: Any) -> LLMProvider:
        providers: dict[str, type[LLMProvider]] = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "openrouter": OpenRouterProvider,
            "ollama": OllamaProvider,
            "vllm": VLLMProvider,
            "azure": AzureProvider,
            "copilot": CopilotProvider,
            "vertex": VertexAIProvider,
            "bedrock": BedrockProvider,
            "groq": GroqProvider,
        }
        if provider not in providers:
            msg = f"Unknown provider: {provider}"
            raise ValueError(msg)
        if api_key is not None:
            kwargs["api_key"] = api_key
        return providers[provider](**kwargs)
