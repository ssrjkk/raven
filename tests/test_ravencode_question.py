from __future__ import annotations

import pytest

from ravencode.runtime.question import Question, QuestionError


class TestQuestion:
    def test_create_minimal(self):
        q = Question(question="Are you sure?")
        assert q.question == "Are you sure?"
        assert q.header == ""
        assert q.options == []
        assert q.multiple is False

    def test_create_with_all_fields(self):
        q = Question(
            question="Pick one?",
            header="Choice",
            options=[{"label": "A", "description": "Option A"}],
            multiple=True,
        )
        assert q.question == "Pick one?"
        assert q.header == "Choice"
        assert len(q.options) == 1
        assert q.multiple is True

    def test_create_dict_fields(self):
        q = Question(question="Test?")
        d = {
            "question": q.question,
            "header": q.header,
            "options": q.options,
            "multiple": q.multiple,
        }
        assert d["question"] == "Test?"

    def test_question_error_exception(self):
        err = QuestionError({"question": "test"})
        assert isinstance(err, Exception)
        assert err.question_data["question"] == "test"

    def test_question_error_raised(self):
        with pytest.raises(QuestionError):
            raise QuestionError({"question": "test"})
