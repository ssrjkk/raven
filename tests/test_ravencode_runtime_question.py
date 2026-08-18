from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ravencode.runtime.question as question_mod
from ravencode.runtime.question import (
    Question,
    QuestionError,
    ask_question,
    set_question_callback,
    stdin_question_callback,
)


@pytest.fixture(autouse=True)
def reset_callback() -> Generator[None, None, None]:
    question_mod._QUESTION_CALLBACK = None
    yield
    question_mod._QUESTION_CALLBACK = None


def _q(**kw) -> Question:
    return Question(question="pick one", options=[{"label": "a", "description": "aa"}, {"label": "b"}], **kw)


class TestAskQuestion:
    async def test_no_callback_raises(self) -> None:
        with pytest.raises(QuestionError) as exc_info:
            await ask_question(_q(header="h"))
        data = exc_info.value.question_data
        assert data["question"] == "pick one"
        assert data["header"] == "h"
        assert data["options"] == [{"label": "a", "description": "aa"}, {"label": "b"}]

    async def test_callback_returns_str(self) -> None:
        async def cb(q: Question) -> str:
            assert q.question == "pick one"
            return "a"

        set_question_callback(cb)
        assert await ask_question(_q()) == "a"

    async def test_callback_returns_non_str(self) -> None:
        async def cb(q: Question) -> int:
            return 42

        set_question_callback(cb)
        assert await ask_question(_q()) == "42"


class TestStdinQuestionCallback:
    async def test_picks_option_by_number(self, monkeypatch) -> None:
        loop = SimpleNamespace(run_in_executor=AsyncMock(return_value="2"))
        monkeypatch.setattr("ravencode.runtime.question.asyncio.get_event_loop", lambda: loop)
        result = await stdin_question_callback(_q())
        assert result == "b"

    async def test_out_of_range_number_returns_raw(self, monkeypatch) -> None:
        loop = SimpleNamespace(run_in_executor=AsyncMock(return_value="9"))
        monkeypatch.setattr("ravencode.runtime.question.asyncio.get_event_loop", lambda: loop)
        result = await stdin_question_callback(_q())
        assert result == "9"

    async def test_zero_returns_raw(self, monkeypatch) -> None:
        loop = SimpleNamespace(run_in_executor=AsyncMock(return_value="0"))
        monkeypatch.setattr("ravencode.runtime.question.asyncio.get_event_loop", lambda: loop)
        result = await stdin_question_callback(_q())
        assert result == "0"

    async def test_custom_answer(self, monkeypatch) -> None:
        loop = SimpleNamespace(run_in_executor=AsyncMock(return_value="custom text"))
        monkeypatch.setattr("ravencode.runtime.question.asyncio.get_event_loop", lambda: loop)
        result = await stdin_question_callback(_q())
        assert result == "custom text"

    async def test_no_options_returns_input(self, monkeypatch) -> None:
        loop = SimpleNamespace(run_in_executor=AsyncMock(return_value="free text"))
        monkeypatch.setattr("ravencode.runtime.question.asyncio.get_event_loop", lambda: loop)
        result = await stdin_question_callback(Question(question="q"))
        assert result == "free text"
