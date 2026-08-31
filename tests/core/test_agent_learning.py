from __future__ import annotations

from typing import Any

import pytest

from raven.core.agents.orchestrator import PlanTracker, ProfileMemory, TaskOutcomeTracker
from raven.core.agents.router import ClassificationResult, FeedbackLoop, get_feedback_loop


class TestPlanTracker:
    def test_initial_state(self) -> None:
        pt = PlanTracker(["a", "b", "c"])
        assert pt.current_step == 0
        assert pt.total_steps == 3
        assert pt.current_description == "a"

    def test_advance_returns_next_step(self) -> None:
        pt = PlanTracker(["a", "b", "c"])
        assert pt.advance() == "b"
        assert pt.current_step == 1
        assert pt.advance() == "c"
        assert pt.advance() is None
        assert pt.current_step == 3

    def test_record_tool_call_and_stale(self) -> None:
        pt = PlanTracker(["a", "b"])
        for _ in range(5):
            pt.record_tool_call()
        assert pt.is_step_stale()

    def test_not_stale_below_threshold(self) -> None:
        pt = PlanTracker(["a", "b"])
        pt.record_tool_call()
        assert not pt.is_step_stale()

    def test_progress_summary(self) -> None:
        pt = PlanTracker(["a", "b"])
        pt.advance()
        summary = pt.progress_summary()
        assert "1/2" in summary
        assert "b" in summary

    def test_status_message_marks_current(self) -> None:
        pt = PlanTracker(["a", "b"])
        msg = pt.build_status_message()
        assert "[>] a" in msg
        assert "[ ] b" in msg
        pt.advance()
        msg = pt.build_status_message()
        assert "[x] a" in msg
        assert "[>] b" in msg


class TestTaskOutcomeTracker:
    def test_default_success_rate(self) -> None:
        toc = TaskOutcomeTracker()
        assert toc.success_rate("coder") == 0.5

    def test_record_success(self) -> None:
        toc = TaskOutcomeTracker()
        toc.record("coder", True)
        toc.record("coder", True)
        assert toc.success_rate("coder") == 1.0
        assert toc.consecutive_errors("coder") == 0

    def test_consecutive_errors(self) -> None:
        toc = TaskOutcomeTracker()
        toc.record("coder", False)
        toc.record("coder", False)
        assert toc.consecutive_errors("coder") == 2
        assert toc.should_escalate("coder")

    def test_success_resets_consecutive_errors(self) -> None:
        toc = TaskOutcomeTracker()
        toc.record("coder", False)
        toc.record("coder", False)
        toc.record("coder", True)
        assert toc.consecutive_errors("coder") == 0

    def test_suggest_profile(self) -> None:
        toc = TaskOutcomeTracker()
        toc.record("coder", False)
        toc.record("coder", False)
        toc.record("coder", False)
        toc.record("debugger", True)
        toc.record("debugger", True)
        sugg = toc.suggest_profile("coder")
        assert sugg == "debugger"

    def test_no_suggestion_when_alone(self) -> None:
        toc = TaskOutcomeTracker()
        toc.record("coder", False)
        assert toc.suggest_profile("coder") is None

    def test_history_capped(self) -> None:
        toc = TaskOutcomeTracker(max_history=3)
        for _ in range(10):
            toc.record("coder", True)
        assert len(toc._outcomes["coder"]) == 3


class TestProfileMemory:
    def test_record_and_get_files(self) -> None:
        pm = ProfileMemory(max_files=2)
        pm.record_file("coder", "a.py")
        pm.record_file("coder", "b.py")
        pm.record_file("coder", "c.py")
        files = pm.get_recent_files("coder")
        assert files == ["b.py", "c.py"]

    def test_most_recent_first(self) -> None:
        pm = ProfileMemory()
        pm.record_file("coder", "a.py")
        pm.record_file("coder", "b.py")
        assert pm.get_recent_files("coder") == ["a.py", "b.py"]
        pm.record_file("coder", "a.py")
        assert pm.get_recent_files("coder")[-1] == "a.py"

    def test_patterns_dedupe(self) -> None:
        pm = ProfileMemory()
        pm.record_pattern("coder", "def")
        pm.record_pattern("coder", "def")
        assert pm.get_patterns("coder") == ["def"]

    def test_context_hint(self) -> None:
        pm = ProfileMemory()
        assert pm.get_context_hint("coder") == ""
        pm.record_file("coder", "a.py")
        hint = pm.get_context_hint("coder")
        assert "a.py" in hint


class TestFeedbackLoop:
    def test_record_updates_rate(self) -> None:
        fb = FeedbackLoop()
        fb.record("fix the bug", "debugger", True)
        fb.record("fix the bug", "debugger", True)
        assert fb._outcomes["debugger"].success_rate == 1.0

    def test_adjusted_confidence_default(self) -> None:
        fb = FeedbackLoop()
        assert fb.get_adjusted_confidence("coder", 0.6) == 0.6

    def test_adjusted_confidence_boosts_high_rate(self) -> None:
        fb = FeedbackLoop()
        for _ in range(3):
            fb.record("write code here", "coder", True)
        adj = fb.get_adjusted_confidence("coder", 0.6)
        assert adj > 0.6

    def test_adjusted_confidence_reduces_low_rate(self) -> None:
        fb = FeedbackLoop()
        for _ in range(3):
            fb.record("write code here", "coder", False)
        adj = fb.get_adjusted_confidence("coder", 0.6)
        assert adj < 0.6

    def test_suggest_alternative(self) -> None:
        fb = FeedbackLoop()
        fb.record("debug the login page", "debugger", False)
        fb.record("debug the login page", "debugger", False)
        fb.record("debug the login page", "debugger", False)
        fb.record("debug the login page", "coder", True)
        fb.record("debug the login page", "coder", True)
        sugg = fb.suggest_alternative("debugger", "debug the login page")
        assert sugg == "coder"

    def test_no_suggestion_without_pattern_hits(self) -> None:
        fb = FeedbackLoop()
        fb.record("debug the login page", "debugger", False)
        fb.record("debug the login page", "debugger", True)
        assert fb.suggest_alternative("debugger", "debug the login page") is None

    def test_status(self) -> None:
        fb = FeedbackLoop()
        fb.record("hello world", "coder", True)
        status = fb.status()
        assert "coder" in status
        assert status["coder"]["successes"] == 1


class TestClassificationResult:
    @pytest.mark.asyncio
    async def test_adjusts_keyword_confidence(self) -> None:
        fb = FeedbackLoop()
        for _ in range(3):
            fb.record("implement a feature", "coder", False)
        result = _keyword_with_feedback("implement a feature", fb)
        assert result.confidence < 0.65


def _keyword_with_feedback(text: str, fb: FeedbackLoop) -> ClassificationResult:
    from raven.core.agents.router import _keyword_classify

    res = _keyword_classify(text)
    assert res is not None
    res.confidence = fb.get_adjusted_confidence(res.profile, res.confidence, text)
    return res
