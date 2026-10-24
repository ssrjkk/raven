"""The loop closed: the adapter the suite just trained is served as a chat provider.

Runs only under RAVEN_ML_SMOKE=1 (the CI ml job); there, torch/transformers/peft missing is an
error rather than a skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ml.conftest import ml_enabled

pytestmark = pytest.mark.ml

if not ml_enabled():
    pytest.skip("training suite runs in the CI ml job (RAVEN_ML_SMOKE=1)", allow_module_level=True)

from raven.core.llm.factory import LLMProviderFactory  # noqa: E402
from raven.core.llm.providers.local import LocalAdapterProvider  # noqa: E402

MESSAGES = [{"role": "user", "content": "count to 2"}]


@pytest.fixture
def provider(trained_adapter: dict[str, object]) -> LocalAdapterProvider:
    adapter = trained_adapter["adapter"]
    assert isinstance(adapter, Path)
    return LocalAdapterProvider(
        base_model=str(trained_adapter["base"]),
        adapter_path=str(adapter),
        max_new_tokens=8,
        temperature=0.0,
    )


class TestLocalAdapterProvider:
    async def test_factory_resolves_local(self, trained_adapter: dict[str, object]) -> None:
        adapter = trained_adapter["adapter"]
        assert isinstance(adapter, Path)
        created = LLMProviderFactory.create(
            "local", base_model=str(trained_adapter["base"]), adapter_path=str(adapter)
        )
        assert isinstance(created, LocalAdapterProvider)

    async def test_complete_returns_generated_text_and_usage(self, provider: LocalAdapterProvider) -> None:
        response = await provider.complete(MESSAGES, model="")
        assert isinstance(response.content, str) and response.content.strip() != ""
        # the prompt must not be echoed back as the answer
        assert not response.content.startswith("user:")
        assert response.usage["prompt_tokens"] > 0
        assert response.usage["completion_tokens"] > 0
        assert response.usage["total_tokens"] == (
            response.usage["prompt_tokens"] + response.usage["completion_tokens"]
        )
        await provider.cleanup()

    async def test_stream_yields_pieces_that_reassemble_the_answer(
        self, provider: LocalAdapterProvider
    ) -> None:
        pieces = [chunk async for chunk in provider.complete_stream(MESSAGES, model="")]
        assert len(pieces) > 0
        assert "".join(pieces).strip() != ""
        await provider.cleanup()

    async def test_tool_requests_are_refused_not_dropped(self, provider: LocalAdapterProvider) -> None:
        tools = [{"type": "function", "function": {"name": "shell.run", "parameters": {}}}]
        with pytest.raises(RuntimeError, match="cannot emit tool calls"):
            await provider.complete(MESSAGES, model="", tools=tools)
        await provider.cleanup()

    async def test_missing_adapter_is_an_explicit_error(self) -> None:
        empty = LocalAdapterProvider(base_model="x/y", adapter_path="")
        with pytest.raises(RuntimeError, match="needs an adapter directory"):
            await empty.complete(MESSAGES, model="")

    async def test_cleanup_releases_the_model(self, provider: LocalAdapterProvider) -> None:
        await provider.complete(MESSAGES, model="")
        assert provider._model is not None
        await provider.cleanup()
        assert provider._model is None
        assert provider._loaded_base == ""
