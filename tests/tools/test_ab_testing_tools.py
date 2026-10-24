from __future__ import annotations

import pytest

import raven.tools.ab_testing as ab_tools
from raven.core.ab_testing import ABTestEngine

VARIANTS = '[{"name":"Control","weight":1.0},{"name":"Treatment","weight":1.0}]'


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch) -> ABTestEngine:
    fresh = ABTestEngine()
    monkeypatch.setattr(ab_tools, "_engine", fresh)
    return fresh


def start(engine: ABTestEngine) -> str:
    created = ab_tools.ab_create("promo", "desc", VARIANTS)
    exp_id = engine.list_experiments()[-1].id
    assert ab_tools.ab_start(exp_id).startswith("Experiment")
    assert "created" in created
    return exp_id


class TestCreateAndDescribe:
    def test_bad_weight_is_reported_as_an_error_not_created(self, engine: ABTestEngine) -> None:
        assert ab_tools.ab_create("x", "d", '[{"name":"a","weight":0},{"name":"b"}]').startswith("[error]")
        assert engine.list_experiments() == []

    def test_get_marks_the_control_arm(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        assert "[control]" in ab_tools.ab_get(exp_id)


class TestRecording:
    def test_unknown_variant_is_not_reported_as_recorded(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        result = ab_tools.ab_record(exp_id, "Typo", "conversion", 1.0, "u1")
        assert result.startswith("[error]")
        assert "is not part of experiment" in result

    def test_success_line_shows_when_a_unit_is_missing(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        result = ab_tools.ab_record(exp_id, "Control", "conversion", 1.0, "")
        assert "no unit of randomization" in result


class TestAssignment:
    def test_assign_without_a_subject_explains_why(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        assert "subject id" in ab_tools.ab_assign(exp_id)

    def test_assign_on_a_draft_is_an_error(self, engine: ABTestEngine) -> None:
        created = ab_tools.ab_create("x", "d", VARIANTS)
        exp_id = created.split("id=")[1].split("]")[0]
        assert "not found or not running" in ab_tools.ab_assign(exp_id, "u1")


class TestResultsText:
    def test_identical_arms_are_not_reported_as_significant(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        for i in range(40):
            ab_tools.ab_record(exp_id, "Control", "conversion", 1.0, f"c{i}")
            ab_tools.ab_record(exp_id, "Treatment", "conversion", 1.0, f"t{i}")
        text = ab_tools.ab_results(exp_id)
        assert "not significant" in text
        assert "Statistically significant!" not in text
        assert "same outcome" in text

    def test_report_names_the_test_alpha_and_sample_size(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        for i in range(300):
            ab_tools.ab_record(exp_id, "Control", "conversion", 1.0 if i % 10 == 0 else 0.0, f"c{i}")
            ab_tools.ab_record(exp_id, "Treatment", "conversion", 1.0 if i % 5 == 0 else 0.0, f"t{i}")
        text = ab_tools.ab_results(exp_id)
        assert "two_proportion_z_on_units" in text
        assert "alpha 0.05" in text
        assert "p_adjusted=" in text
        assert "95% CI" in text
        assert "significant" in text
        assert "units, not events, are the sample size" in text

    def test_lift_undefined_is_stated_instead_of_zero_percent(self, engine: ABTestEngine) -> None:
        exp_id = start(engine)
        for i in range(40):
            ab_tools.ab_record(exp_id, "Control", "conversion", 0.0, f"c{i}")
            ab_tools.ab_record(exp_id, "Treatment", "conversion", 1.0, f"t{i}")
        text = ab_tools.ab_results(exp_id)
        assert "lift=undefined (control mean is 0)" in text
        assert "lift=0.00%" not in text
