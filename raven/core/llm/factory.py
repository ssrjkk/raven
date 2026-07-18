from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from raven.core.llm._legacy import (
    AnthropicProvider,
    AzureProvider,
    BedrockProvider,
    CopilotProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
    VertexAIProvider,
    VLLMProvider,
)
from raven.core.llm.protocol import LLMProvider


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
        }
        if provider not in providers:
            raise ValueError(f"Unknown provider: {provider}")
        if api_key is not None:
            kwargs["api_key"] = api_key
        return providers[provider](**kwargs)
