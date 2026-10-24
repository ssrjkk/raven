from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any

import pytest

from raven.core.ab_testing import ABTestEngine, Experiment


@pytest.fixture()
def engine() -> ABTestEngine:
    return ABTestEngine()


def results_of(engine: ABTestEngine, experiment_id: str) -> dict[str, Any]:
    results = engine.get_results(experiment_id)
    assert results is not None
    return results


def assigned(engine: ABTestEngine, experiment_id: str, user_id: str) -> str:
    variant = engine.assign_variant(experiment_id, user_id)
    assert variant is not None
    return variant


def make_running(
    engine: ABTestEngine, variants: list[dict[str, Any]], **kwargs: Any
) -> Experiment:
    exp = engine.create_experiment("exp", "desc", variants, **kwargs)
    started = engine.start_experiment(exp.id)
    assert started is not None
    return started


class TestExperimentCreation:
    def test_first_variant_becomes_the_control_when_none_is_marked(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        assert exp.control.name == "a"

    def test_marked_control_is_respected_even_when_not_first(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b", "is_control": True}])
        assert exp.control.name == "b"

    def test_single_variant_is_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="at least 2 variants"):
            engine.create_experiment("x", "d", [{"name": "only"}])

    def test_duplicate_variant_names_are_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="duplicate variant name"):
            engine.create_experiment("x", "d", [{"name": "a"}, {"name": "a"}])

    def test_two_controls_are_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="only one variant may be the control"):
            engine.create_experiment("x", "d", [{"name": "a", "is_control": True}, {"name": "b", "is_control": True}])

    @pytest.mark.parametrize("weight", [0, -1, "0.5", True, math.nan, math.inf])
    def test_unusable_weights_are_rejected(self, engine: ABTestEngine, weight: object) -> None:
        with pytest.raises(ValueError):
            engine.create_experiment("x", "d", [{"name": "a", "weight": weight}, {"name": "b"}])

    def test_weight_the_splitter_cannot_represent_is_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="never be assigned"):
            engine.create_experiment("x", "d", [{"name": "a", "weight": 0.99999}, {"name": "b", "weight": 1e-6}])

    def test_empty_variant_name_is_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="non-empty name"):
            engine.create_experiment("x", "d", [{"name": " "}, {"name": "b"}])

    def test_unknown_metric_type_is_rejected(self, engine: ABTestEngine) -> None:
        with pytest.raises(ValueError, match="metric_type must be one of"):
            engine.create_experiment("x", "d", [{"name": "a"}, {"name": "b"}], metric_type="median")


class TestAssignment:
    def test_same_user_always_gets_the_same_arm(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        arms = {engine.assign_variant(exp.id, "user-1") for _ in range(50)}
        assert arms == {engine.assign_variant(exp.id, "user-1")}

    def test_different_users_are_split_close_to_the_configured_weights(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a", "weight": 3}, {"name": "b", "weight": 7}])
        counts = {"a": 0, "b": 0}
        total = 20000
        for i in range(total):
            counts[assigned(engine, exp.id, f"u{i}")] += 1
        assert abs(counts["a"] / total - 0.3) < 0.01
        assert abs(counts["b"] / total - 0.7) < 0.01

    def test_boundary_weight_does_not_leak_traffic_into_the_other_arm(self, engine: ABTestEngine) -> None:
        # a 1-1 split must not systematically favour the first arm, which the old <= boundary did
        exp = make_running(engine, [{"name": "a", "weight": 1}, {"name": "b", "weight": 1}])
        first = sum(1 for i in range(20000) if assigned(engine, exp.id, f"u{i}") == "a")
        assert abs(first / 20000 - 0.5) < 0.01

    def test_requires_a_subject_id(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        with pytest.raises(ValueError, match="needs a subject id"):
            engine.assign_variant(exp.id, "")

    def test_draft_experiment_assigns_nothing(self, engine: ABTestEngine) -> None:
        exp = engine.create_experiment("x", "d", [{"name": "a"}, {"name": "b"}])
        assert engine.assign_variant(exp.id, "u1") is None

    def test_unknown_experiment_assigns_nothing(self, engine: ABTestEngine) -> None:
        assert engine.assign_variant("missing", "u1") is None


class TestRecording:
    def test_unknown_variant_is_refused_not_dropped(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        with pytest.raises(ValueError, match="is not part of experiment"):
            engine.record_event(exp.id, "typo", "conversion", 1.0, "u1")

    def test_other_metric_is_refused(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        with pytest.raises(ValueError, match="measures 'conversion'"):
            engine.record_event(exp.id, "a", "latency", 1.0, "u1")

    def test_rate_metric_rejects_values_outside_the_unit_interval(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        with pytest.raises(ValueError, match=r"requires a value in \[0, 1\]"):
            engine.record_event(exp.id, "a", "conversion", 7.0, "u1")

    @pytest.mark.parametrize("value", [math.nan, math.inf, "1.0", True])
    def test_non_finite_or_non_numeric_values_are_refused(self, engine: ABTestEngine, value: object) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}], metric_type="mean")
        with pytest.raises(ValueError, match="finite number"):
            engine.record_event(exp.id, "a", "conversion", value, "u1")  # type: ignore[arg-type]

    def test_unknown_experiment_raises_keyerror(self, engine: ABTestEngine) -> None:
        with pytest.raises(KeyError):
            engine.record_event("missing", "a", "conversion", 1.0, "u1")

    def test_mean_metric_accepts_values_above_one(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}], metric_name="latency", metric_type="mean")
        event = engine.record_event(exp.id, "a", "latency", 930.5, "u1")
        assert event.experiment_id == exp.id and event.value == 930.5

    def test_event_cap_is_visible_instead_of_silent(self) -> None:
        engine = ABTestEngine(max_events_per_experiment=3)
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        for i in range(3):
            engine.record_event(exp.id, "a", "conversion", 1.0, f"u{i}")
        with pytest.raises(RuntimeError, match="event cap"):
            engine.record_event(exp.id, "b", "conversion", 1.0, "u9")
        results = results_of(engine, exp.id)
        assert results is not None and results["events_dropped"] == 1


class TestOwnership:
    def test_experiments_do_not_share_events(self, engine: ABTestEngine) -> None:
        first = make_running(engine, [{"name": "x"}, {"name": "y"}])
        second = make_running(engine, [{"name": "x"}, {"name": "y"}])
        for i in range(50):
            engine.record_event(first.id, "x", "conversion", 1.0, f"u{i}")
        assert results_of(engine, first.id)["total_events"] == 50
        assert results_of(engine, second.id)["total_events"] == 0

    def test_deleted_experiment_does_not_leave_events_behind(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "x"}, {"name": "y"}])
        for i in range(10):
            engine.record_event(exp.id, "x", "conversion", 1.0, f"u{i}")
        assert engine.delete_experiment(exp.id) is True
        assert engine.get_results(exp.id) is None
        reuse = make_running(engine, [{"name": "x"}, {"name": "y"}])
        assert results_of(engine, reuse.id)["total_events"] == 0

    def test_events_of_a_removed_variant_are_reported_not_vanished(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}, {"name": "c"}])
        for i in range(20):
            engine.record_event(exp.id, "a", "conversion", 1.0, f"u{i}")
            engine.record_event(exp.id, "c", "conversion", 1.0, f"w{i}")
        engine.update_experiment(exp.id, variants=[{"name": "a"}, {"name": "b"}])
        results = results_of(engine, exp.id)
        assert results["events_orphaned"] == 20
        assert results["events_stored"] == 40
        assert any("no longer exist" in w for w in results["warnings"])


class TestUnitsAreTheSampleSize:
    def test_one_user_with_many_events_is_one_unit(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}], metric_name="m", metric_type="mean")
        for _ in range(60):
            engine.record_event(exp.id, "c", "m", 1.0, "solo")
            engine.record_event(exp.id, "t", "m", 2.0, "solo")
        results = results_of(engine, exp.id)
        assert results["unit_counts"] == {"c": 1, "t": 1}
        assert results["variants"][0]["events"] == 60
        assert results["comparisons"][0]["p_value"] == 1.0
        assert results["significant"] is False

    def test_the_same_events_from_many_users_are_many_units(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}], metric_name="m", metric_type="mean")
        for i in range(60):
            engine.record_event(exp.id, "c", "m", 1.0, f"c{i}")
            engine.record_event(exp.id, "t", "m", 2.0, f"t{i}")
        results = results_of(engine, exp.id)
        assert results["unit_counts"] == {"c": 60, "t": 60}
        assert results["significant"] is True

    def test_events_without_a_user_are_counted_and_excluded(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        for _ in range(30):
            engine.record_event(exp.id, "a", "conversion", 1.0, "")
        results = results_of(engine, exp.id)
        assert results["events_unattributed"] == 30
        assert results["unit_counts"] == {"a": 0, "b": 0}
        assert any("no user_id" in w for w in results["warnings"])

    def test_a_user_converts_if_any_of_their_events_converted(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "a"}, {"name": "b"}])
        engine.record_event(exp.id, "a", "conversion", 0.0, "u1")
        engine.record_event(exp.id, "a", "conversion", 1.0, "u1")
        results = results_of(engine, exp.id)
        assert results["variants"][0]["unit_avg"] == 1.0
        assert results["unit_counts"]["a"] == 1


class TestStatistics:
    def test_report_is_scale_invariant_on_a_continuous_metric(self, engine: ABTestEngine) -> None:
        def run(factor: float) -> float:
            local = ABTestEngine()
            exp = make_running(
                local, [{"name": "s"}, {"name": "f"}], metric_name="latency", metric_type="mean"
            )
            rng = random.Random(11)
            for i in range(60):
                local.record_event(exp.id, "s", "latency", rng.gauss(2.5, 0.4) * factor, f"u{i}")
                local.record_event(exp.id, "f", "latency", rng.gauss(2.4, 0.4) * factor, f"v{i}")
            results = local.get_results(exp.id)
            assert results is not None
            return float(results["comparisons"][0]["p_value"])

        assert run(1.0) == pytest.approx(run(1000.0), rel=1e-9)

    def test_identical_arms_are_never_significant(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        for i in range(40):
            engine.record_event(exp.id, "c", "conversion", 1.0, f"u{i}")
            engine.record_event(exp.id, "t", "conversion", 1.0, f"v{i}")
        results = results_of(engine, exp.id)
        assert results["comparisons"][0]["p_value"] == 1.0
        assert results["significant"] is False
        assert any("same outcome" in w for w in results["warnings"])

    def test_lift_is_undefined_when_the_control_baseline_is_zero(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        for i in range(40):
            engine.record_event(exp.id, "c", "conversion", 0.0, f"u{i}")
            engine.record_event(exp.id, "t", "conversion", 1.0, f"v{i}")
        comparison = results_of(engine, exp.id)["comparisons"][0]
        assert comparison["lift"] is None
        assert comparison["diff"] == pytest.approx(1.0)
        assert comparison["p_value"] < 1e-9

    def test_every_non_control_arm_is_compared(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "b"}, {"name": "d"}])
        for i in range(200):
            engine.record_event(exp.id, "c", "conversion", 1.0 if i % 10 == 0 else 0.0, f"c{i}")
            engine.record_event(exp.id, "b", "conversion", 1.0 if i % 10 == 0 else 0.0, f"b{i}")
            engine.record_event(exp.id, "d", "conversion", 1.0 if i % 3 == 0 else 0.0, f"d{i}")
        results = results_of(engine, exp.id)
        compared = {c["variant"] for c in results["comparisons"]}
        assert compared == {"b", "d"}
        assert results["comparisons"][1]["significant"] is True

    def test_holm_is_applied_across_the_comparisons(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "b"}, {"name": "d"}])
        for i in range(120):
            engine.record_event(exp.id, "c", "conversion", 1.0 if i % 4 == 0 else 0.0, f"c{i}")
            engine.record_event(exp.id, "b", "conversion", 1.0 if i % 4 == 0 else 0.0, f"b{i}")
            engine.record_event(exp.id, "d", "conversion", 1.0 if i % 4 == 0 else 0.0, f"d{i}")
        comparisons = results_of(engine, exp.id)["comparisons"]
        assert all(c["p_adjusted"] >= c["p_value"] for c in comparisons)
        assert len({c["p_adjusted"] for c in comparisons}) == 1  # identical arms share one adjusted p

    def test_a_real_effect_is_detected(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        for i in range(1500):
            engine.record_event(exp.id, "c", "conversion", 1.0 if i % 10 == 0 else 0.0, f"c{i}")
            engine.record_event(exp.id, "t", "conversion", 1.0 if i % 5 == 0 else 0.0, f"t{i}")
        comparison = results_of(engine, exp.id)["comparisons"][0]
        assert comparison["significant"] is True
        assert comparison["diff"] == pytest.approx(0.1, abs=0.01)

    def test_method_and_control_are_part_of_the_report(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        results = results_of(engine, exp.id)
        assert results["method"] == "two_proportion_z_on_units"
        assert results["control"] == "c"
        assert results["alpha"] == 0.05
        assert results["multiplicity"] == "holm-bonferroni"

    def test_continuous_metric_uses_the_welch_test(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}], metric_name="m", metric_type="mean")
        rng = random.Random(3)
        for i in range(80):
            engine.record_event(exp.id, "c", "m", rng.gauss(1.0, 0.3), f"c{i}")
            engine.record_event(exp.id, "t", "m", rng.gauss(1.05, 0.3), f"t{i}")
        results = results_of(engine, exp.id)
        assert results["method"] == "welch_t_on_unit_means"
        assert results["comparisons"][0]["test"] == "welch_t"


class TestFalsePositiveControl:
    @pytest.mark.parametrize(("metric_type", "draw"), [
        ("rate", lambda r: 1.0 if r.random() < 0.3 else 0.0),
        ("mean", lambda r: r.gauss(1.0, 0.5)),
    ])
    def test_aa_experiments_only_fire_at_the_nominal_rate(
        self, metric_type: str, draw: Callable[[random.Random], float]
    ) -> None:
        engine = ABTestEngine()
        trials = 200
        hits = 0
        for t in range(trials):
            exp = make_running(
                engine, [{"name": "c"}, {"name": "t"}], metric_name="m", metric_type=metric_type
            )
            rng = random.Random(t)
            for i in range(80):
                engine.record_event(exp.id, "c", "m", draw(rng), f"c{t}-{i}")
                engine.record_event(exp.id, "t", "m", draw(rng), f"t{t}-{i}")
            hits += 1 if results_of(engine, exp.id)["significant"] else 0
        rate = hits / trials
        assert 0.0 <= rate <= 0.12, f"A/A false positive rate {rate:.3f} is far from alpha 0.05"


class TestSampleRatioMismatch:
    def test_one_arm_never_receiving_traffic_is_flagged(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        for i in range(200):
            engine.record_event(exp.id, "c", "conversion", 1.0 if i % 2 else 0.0, f"c{i}")
            engine.record_event(exp.id, "c", "conversion", 1.0 if i % 3 else 0.0, f"t{i}")
        results = results_of(engine, exp.id)
        assert results["srm"]["imbalanced"] is True
        assert any("sample ratio mismatch" in w for w in results["warnings"])

    def test_a_balanced_experiment_is_not_flagged(self, engine: ABTestEngine) -> None:
        exp = make_running(engine, [{"name": "c"}, {"name": "t"}])
        for i in range(100):
            engine.record_event(exp.id, "c", "conversion", 1.0, f"c{i}")
            engine.record_event(exp.id, "t", "conversion", 1.0, f"t{i}")
        assert results_of(engine, exp.id)["srm"]["imbalanced"] is False
