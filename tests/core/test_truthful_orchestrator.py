# ruff: noqa: RUF001 (intentional Cyrillic in Russian prompts)

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from raven.core.llm.protocol import LLMResponse


class ScriptedCompleter:
    """Real (non-mock) LLMClientProtocol implementation that replays canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.prompts.append(messages[-1]["content"])
        if not self._responses:
            return LLMResponse(content="")
        return LLMResponse(content=self._responses.pop(0))

    async def complete_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        yield ""


def make_orchestrator(responses: list[str], max_corrections: int = 1):
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    completer = ScriptedCompleter(responses)
    return TruthfulOrchestrator(completer, model="test-model", max_corrections=max_corrections), completer


@pytest.mark.asyncio
async def test_success_keeps_clean_answer_and_thinking():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>Проверяю факты: функция существует в API.</thinking>\nОтвет: функция compute() есть.",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("Что делает compute()?")
    assert result.status == "success"
    assert result.content == "Ответ: функция compute() есть."
    assert result.thinking_process == "Проверяю факты: функция существует в API."


@pytest.mark.asyncio
async def test_thinking_case_insensitive():
    orchestrator, _completer = make_orchestrator(
        [
            "<THINKING>Рассуждение</THINKING>\nИтог",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "success"
    assert result.content == "Итог"


@pytest.mark.asyncio
async def test_missing_thinking_block_returns_fallback():
    orchestrator, _completer = make_orchestrator(["Ответ без мышления.", "VERIFIED: TRUE"])
    result = await orchestrator.process("q")
    assert result.status == "success"
    assert result.thinking_process == "Мышление не предоставлено (нарушение протокола)."


@pytest.mark.asyncio
async def test_refused_when_insufficient_data():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>Нет контекста по этому модулю.</thinking>\n"
            "У меня недостаточно данных для точного ответа. Пожалуйста, предоставьте исходный код.",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("Как работает модуль X?")
    assert result.status == "refused"
    assert "недостаточно данных" in result.content


@pytest.mark.asyncio
async def test_verified_false_triggers_correction():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>Проверяю.</thinking>\nВыдуманный ответ",
            "VERIFIED: FALSE: метод foo() не существует в API.",
            "<thinking>Исправляю.</thinking>\nИсправленный ответ",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "Исправленный ответ"


@pytest.mark.asyncio
async def test_correction_loop_bounded_by_max_corrections():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>a</thinking>\nчерновик",
            "VERIFIED: FALSE: ошибка 1",
            "<thinking>b</thinking>\nвторая попытка",
            "VERIFIED: FALSE: ошибка 2",
            "<thinking>c</thinking>\nфинальная попытка",
            "VERIFIED: TRUE",
        ],
        max_corrections=2,
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "финальная попытка"
    assert len(_completer.prompts) == 6


@pytest.mark.asyncio
async def test_single_correction_default_limit():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>a</thinking>\nчерновик",
            "VERIFIED: FALSE: ошибка",
            "<thinking>b</thinking>\nисправлено",
            "VERIFIED: FALSE: всё ещё ложь",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "исправлено"
    assert len(_completer.prompts) == 4


@pytest.mark.asyncio
async def test_verified_true_requires_no_correction_call():
    orchestrator, _completer = make_orchestrator(["<thinking>ok</thinking>\nответ", "verified: TRUE"])
    result = await orchestrator.process("q")
    assert result.status == "success"
    assert len(_completer.prompts) == 2


@pytest.mark.asyncio
async def test_empty_verification_is_not_success():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>ok</thinking>\nчерновик",
            "",
            "<thinking>исправлено</thinking>\nисправленный ответ",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "исправленный ответ"


@pytest.mark.asyncio
async def test_unclear_verification_triggers_correction():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>ok</thinking>\nчерновик",
            "Вот размышления аудитора...",
            "<thinking>перепроверено</thinking>\nисправленный ответ",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "исправленный ответ"


@pytest.mark.asyncio
async def test_verdict_must_be_at_line_start():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>ok</thinking>\nчерновик",
            "Текст содержит 'VERIFIED: TRUE' внутри строки, но это не вердикт.",
            "<thinking>второй</thinking>\nисправленный ответ",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "исправленный ответ"
    assert len(_completer.prompts) == 4


@pytest.mark.asyncio
async def test_ambiguous_final_verdict_not_reported_success():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>ok</thinking>\nчерновик",
            "garbage",
            "<thinking>попытка</thinking>\nисправленный ответ",
            "garbage again",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert result.content == "исправленный ответ"


@pytest.mark.asyncio
async def test_correction_uses_updated_thinking_in_verifier():
    orchestrator, completer = make_orchestrator(
        [
            "<thinking>ПЕРВОЕ</thinking>\nчерновик",
            "VERIFIED: FALSE: исправь",
            "<thinking>ВТОРОЕ</thinking>\nисправленный ответ",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "corrected"
    assert "ВТОРОЕ" in completer.prompts[3]
    assert result.thinking_process == "ВТОРОЕ"


@pytest.mark.asyncio
async def test_timeout_raises():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    class SlowCompleter(ScriptedCompleter):
        def __init__(self, delay: float) -> None:
            super().__init__(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
            self.delay = delay

        async def complete(
            self,
            messages: list[dict[str, Any]],
            model: str | None = None,
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            await asyncio.sleep(self.delay)
            return await super().complete(messages, model=model, tools=tools)

    orchestrator = TruthfulOrchestrator(SlowCompleter(0.2), model="", timeout=0.05)
    with pytest.raises(TimeoutError):
        await orchestrator.process("q")


def test_negative_max_corrections_rejected():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    with pytest.raises(ValueError):
        TruthfulOrchestrator(ScriptedCompleter([]), model="", max_corrections=-1)


def test_nonpositive_timeout_rejected():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    with pytest.raises(ValueError):
        TruthfulOrchestrator(ScriptedCompleter([]), model="", timeout=0)


def test_invalid_max_input_chars_rejected():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    with pytest.raises(ValueError):
        TruthfulOrchestrator(ScriptedCompleter([]), model="", max_input_chars=0)


@pytest.mark.asyncio
async def test_oversized_query_rejected():
    orchestrator, _completer = make_orchestrator(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
    with pytest.raises(ValueError):
        await orchestrator.process("x" * 20_001)


@pytest.mark.asyncio
async def test_oversized_context_rejected():
    orchestrator, _completer = make_orchestrator(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
    with pytest.raises(ValueError):
        await orchestrator.process("q", context="x" * 20_001)


@pytest.mark.asyncio
async def test_refusal_alternative_marker():
    orchestrator, _completer = make_orchestrator(
        [
            "<thinking>нет данных</thinking>\nНе хватает данных для ответа.",
            "VERIFIED: TRUE",
        ]
    )
    result = await orchestrator.process("q")
    assert result.status == "refused"


@pytest.mark.asyncio
async def test_primary_prompt_wraps_user_content():
    orchestrator, completer = make_orchestrator(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
    await orchestrator.process("напиши стих", context="фрагмент кода")
    first = completer.prompts[0]
    assert "<user_query>" in first
    assert "напиши стих" in first
    assert "<context>" in first
    assert "фрагмент кода" in first


@pytest.mark.asyncio
async def test_context_injected_into_primary_prompt():
    orchestrator, completer = make_orchestrator(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
    await orchestrator.process("q", context="PROJECT_SNIPPET")
    assert "PROJECT_SNIPPET" in completer.prompts[0]


@pytest.mark.asyncio
async def test_model_passed_to_completer():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    class CapturingCompleter(ScriptedCompleter):
        def __init__(self) -> None:
            super().__init__(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
            self.models: list[str | None] = []

        async def complete(
            self,
            messages: list[dict[str, Any]],
            model: str | None = None,
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            self.models.append(model)
            return await super().complete(messages, model=model, tools=tools)

    completer = CapturingCompleter()
    orchestrator = TruthfulOrchestrator(completer, model="qwen/qwen-2.5-72b-instruct")
    await orchestrator.process("q")
    assert all(m == "qwen/qwen-2.5-72b-instruct" for m in completer.models)


@pytest.mark.asyncio
async def test_correction_prompt_contains_verifier_feedback():
    orchestrator, completer = make_orchestrator(
        [
            "<thinking>a</thinking>\nчерновик",
            "VERIFIED: FALSE: нет такого метода",
            "<thinking>b</thinking>\nисправлено",
            "VERIFIED: TRUE",
        ]
    )
    await orchestrator.process("q")
    assert "нет такого метода" in completer.prompts[2]


@pytest.mark.asyncio
async def test_verifier_receives_thinking_and_draft():
    orchestrator, completer = make_orchestrator(["<thinking>M</thinking>\nDRAFT", "VERIFIED: TRUE"])
    await orchestrator.process("q")
    verifier_prompt = completer.prompts[1]
    assert "M" in verifier_prompt
    assert "DRAFT" in verifier_prompt


@pytest.mark.asyncio
async def test_empty_model_string_ok():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    completer = ScriptedCompleter(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"])
    orchestrator = TruthfulOrchestrator(completer, model="")
    result = await orchestrator.process("q")
    assert result.status == "success"


@pytest.mark.asyncio
async def test_llmrouter_structural_compatibility():
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    orchestrator = TruthfulOrchestrator(ScriptedCompleter(["<thinking>ok</thinking>\nответ", "VERIFIED: TRUE"]), model="")
    assert orchestrator._model == ""
