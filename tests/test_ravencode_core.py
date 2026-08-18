from __future__ import annotations

import pytest

from ravencode.core import prompts as prompts_mod
from ravencode.core.metrics import observe_llm, observe_tool
from ravencode.core.prompts import (
    PLANNER,
    SYSTEM,
    get_prompt,
    register_prompt,
)


class TestGetPrompt:
    def test_known_types(self) -> None:
        for prompt_type in prompts_mod._PROMPTS:
            assert get_prompt(prompt_type)

    def test_system_prompt_content(self) -> None:
        assert "Raven" in get_prompt(SYSTEM)

    def test_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown prompt type: bogus"):
            get_prompt("bogus")

    def test_kwargs_without_placeholders(self) -> None:
        assert get_prompt(SYSTEM, extra="ignored") == get_prompt(SYSTEM)

    def test_kwargs_formatted(self) -> None:
        register_prompt("fmt_test", "Hi {name}!")
        assert get_prompt("fmt_test", name="Alice") == "Hi Alice!"

    def test_planner_prompt(self) -> None:
        assert "planning" in get_prompt(PLANNER)


class TestRegisterPrompt:
    def test_register_and_get(self) -> None:
        register_prompt("my_prompt", "content")
        assert get_prompt("my_prompt") == "content"

    def test_register_overwrites(self) -> None:
        register_prompt("overwrite_me", "first")
        register_prompt("overwrite_me", "second")
        assert get_prompt("overwrite_me") == "second"


class TestObserveLlm:
    async def test_increments_and_returns(self) -> None:
        before = counters_llm("test_provider", "test_model")
        value = []

        @observe_llm(provider="test_provider", model="test_model")
        async def my_func(x: int) -> int:
            value.append(x)
            return x * 2

        assert await my_func(21) == 42
        assert value == [21]
        assert counters_llm("test_provider", "test_model") == before + 1

    async def test_wraps_preserves_name(self) -> None:
        @observe_llm(provider="p", model="m")
        async def named_func() -> None: ...

        assert named_func.__name__ == "named_func"


class TestObserveTool:
    async def test_increments_and_returns(self) -> None:
        before = counters_tool("test_tool")
        observed = []

        @observe_tool(tool_name="test_tool")
        async def my_tool(a: str) -> str:
            observed.append(a)
            return a.upper()

        assert await my_tool("hi") == "HI"
        assert observed == ["hi"]
        assert counters_tool("test_tool") == before + 1

    async def test_wraps_preserves_name(self) -> None:
        @observe_tool(tool_name="t")
        async def tool_func() -> None: ...

        assert tool_func.__name__ == "tool_func"


def counters_llm(provider: str, model: str) -> int:
    from ravencode.core.metrics import llm_requests_total

    return int(llm_requests_total.labels(provider=provider, model=model)._value.get())


def counters_tool(tool_name: str) -> int:
    from ravencode.core.metrics import tool_execution_total

    return int(tool_execution_total.labels(tool_name=tool_name)._value.get())
