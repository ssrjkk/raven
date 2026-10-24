from __future__ import annotations

import math

import pytest

from raven.core.ab_stats import (
    _normal_critical,
    _z_critical,
    betainc,
    chi2_sf,
    holm_adjust,
    mean_and_variance,
    permutation_test,
    srm_check,
    t_two_sided_p,
    two_proportion_test,
    welch_test,
    wilson_interval,
)


class TestSpecialFunctions:
    def test_student_t_matches_textual_critical_value(self) -> None:
        assert t_two_sided_p(2.228138852, 10) == pytest.approx(0.05, abs=1e-8)

    def test_student_t_at_one_degree_of_freedom_is_cauchy(self) -> None:
        expected = 1.0 - 2.0 * math.atan(1.0) / math.pi
        assert t_two_sided_p(1.0, 1) == pytest.approx(expected, abs=1e-9)

    def test_t_p_decreases_as_t_grows(self) -> None:
        assert t_two_sided_p(0.0, 20) == pytest.approx(1.0, abs=1e-9)
        assert t_two_sided_p(1.0, 20) > t_two_sided_p(2.0, 20) > t_two_sided_p(4.0, 20)

    def test_chi_square_known_values(self) -> None:
        assert chi2_sf(3.8414588, 1) == pytest.approx(0.05, abs=1e-6)
        assert chi2_sf(0.4549364, 1) == pytest.approx(0.5, abs=1e-6)
        assert chi2_sf(5.9914645, 2) == pytest.approx(0.05, abs=1e-6)
        assert chi2_sf(12.8325, 5) == pytest.approx(0.025, abs=1e-5)

    def test_chi_square_bounds(self) -> None:
        assert chi2_sf(0.0, 3) == 1.0
        assert chi2_sf(-1.0, 3) == 1.0
        assert chi2_sf(1e6, 3) == pytest.approx(0.0, abs=1e-12)

    def test_betainc_endpoints_and_symmetry(self) -> None:
        assert betainc(2.0, 3.0, 0.0) == 0.0
        assert betainc(2.0, 3.0, 1.0) == 1.0
        assert betainc(2.0, 2.0, 0.5) == pytest.approx(0.5, abs=1e-12)


class TestCriticalValues:
    def test_normal_critical_values(self) -> None:
        assert _normal_critical(0.05) == pytest.approx(1.959963985, abs=1e-6)
        assert _normal_critical(0.01) == pytest.approx(2.575829304, abs=1e-6)

    def test_t_critical_values(self) -> None:
        assert _z_critical(0.05, 10) == pytest.approx(2.228138852, abs=1e-6)
        assert _z_critical(0.05, 1) == pytest.approx(12.70622, abs=1e-4)

    def test_t_critical_approaches_normal_as_df_grows(self) -> None:
        assert _z_critical(0.05, 100_000) == pytest.approx(_normal_critical(0.05), abs=1e-3)


class TestWilson:
    def test_known_interval(self) -> None:
        low, high = wilson_interval(287, 1000)
        assert low == pytest.approx(0.25982, abs=1e-4)
        assert high == pytest.approx(0.31581, abs=1e-4)

    def test_saturated_arms_stay_inside_zero_one(self) -> None:
        low_40, high_40 = wilson_interval(40, 40)
        assert low_40 == pytest.approx(0.91238, abs=1e-5)
        assert high_40 == 1.0
        low, high = wilson_interval(0, 40)
        assert low == 0.0
        assert high == pytest.approx(0.08762, abs=1e-5)

    def test_empty_denominator(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 1.0)


class TestPermutationTest:
    def test_matches_closed_form_hypergeometric_tail(self) -> None:
        p = permutation_test([1.0] * 60, [2.0] * 60)
        assert p == pytest.approx(2.0 / math.comb(120, 60), rel=1e-9)

    def test_small_case_is_exactly_one_third(self) -> None:
        assert permutation_test([1.0] * 2, [2.0] * 2) == pytest.approx(1 / 3, rel=1e-12)

    def test_identical_constant_arms_have_no_evidence(self) -> None:
        assert permutation_test([2.0] * 30, [2.0] * 30) == 1.0

    def test_returns_none_when_arms_are_not_constant(self) -> None:
        assert permutation_test([1.0, 2.5, 3.0], [4.0, 5.0, 6.0]) is None


class TestWelch:
    def test_separates_clearly_different_distributions(self) -> None:
        control = [10.0 + (i % 5) for i in range(50)]
        treatment = [14.0 + (i % 5) for i in range(50)]
        result = welch_test(control, treatment)
        assert result["p_value"] < 1e-12
        assert result["diff"] == pytest.approx(4.0)
        assert result["ci_low"] > 3.0 and result["ci_high"] < 5.0

    def test_does_not_invent_evidence_for_identical_samples(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        result = welch_test(values, values)
        assert result["p_value"] == pytest.approx(1.0, abs=1e-9)
        assert result["diff"] == 0.0
        assert result["ci_low"] == pytest.approx(-result["ci_high"], rel=1e-9)
        assert result["ci_low"] < 0 < result["ci_high"]

    def test_below_two_units_is_not_testable(self) -> None:
        result = welch_test([1.0], [2.0, 3.0])
        assert result["p_value"] == 1.0
        assert "fewer than 2 units" in result["warning"]

    def test_zero_variance_different_constants_uses_exact_randomization(self) -> None:
        result = welch_test([1.0] * 40, [2.0] * 40)
        assert result["p_value"] == pytest.approx(2.0 / math.comb(80, 40), rel=1e-9)
        assert "randomization" in result["warning"]

    def test_zero_variance_same_constant_is_a_tie(self) -> None:
        result = welch_test([1.0] * 40, [1.0] * 40)
        assert result["p_value"] == 1.0

    def test_scale_changes_p_only_through_noise_not_through_units(self) -> None:
        control = [1.0, 1.4, 0.8, 1.2, 1.1, 0.9, 1.3, 1.05]
        treatment = [1.6, 1.3, 1.9, 1.4, 1.7, 2.0, 1.5, 1.8]
        seconds = welch_test(control, treatment)["p_value"]
        ms = welch_test([v * 1000 for v in control], [v * 1000 for v in treatment])["p_value"]
        assert seconds == pytest.approx(ms, rel=1e-9)

    def test_mean_and_variance_uses_n_minus_one(self) -> None:
        mean, var, n = mean_and_variance([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert (mean, n) == (5.0, 8)
        assert var == pytest.approx(32 / 7, rel=1e-12)


class TestTwoProportion:
    def test_moderate_difference_matches_reference_computation(self) -> None:
        result = two_proportion_test(12, 40, 20, 40)
        assert result["p_value"] == pytest.approx(0.0679, abs=1e-3)
        assert result["ci_low"] == pytest.approx(-0.0138, abs=2e-3)
        assert result["ci_high"] == pytest.approx(0.3901, abs=2e-3)

    def test_complete_separation_is_significant_not_neutral(self) -> None:
        result = two_proportion_test(0, 40, 40, 40)
        assert result["p_value"] < 1e-9
        assert result["diff"] == pytest.approx(1.0)

    def test_interval_and_p_value_never_disagree_about_zero(self) -> None:
        for successes_c, successes_t in ((0, 40), (12, 20), (2, 30), (20, 20), (18, 25)):
            result = two_proportion_test(successes_c, 40, successes_t, 40)
            contains_zero = result["ci_low"] <= 0 <= result["ci_high"]
            assert (result["p_value"] < 0.05) == (not contains_zero), (successes_c, successes_t)

    def test_interval_stays_inside_the_physical_range(self) -> None:
        for successes_c, successes_t in ((0, 0), (0, 40), (40, 0), (40, 40), (20, 21)):
            result = two_proportion_test(successes_c, 40, successes_t, 40)
            assert -1.0 <= result["ci_low"] <= result["ci_high"] <= 1.0

    def test_both_arms_same_answer_is_a_tie(self) -> None:
        for successes in (0, 40):
            result = two_proportion_test(successes, 40, successes, 40)
            assert result["p_value"] == 1.0
            assert "same outcome" in result["warning"]


class TestHolm:
    def test_step_down_is_monotone(self) -> None:
        assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]

    def test_single_comparison_unchanged(self) -> None:
        assert holm_adjust([0.03]) == [0.03]

    def test_empty_input(self) -> None:
        assert holm_adjust([]) == []

    def test_capped_at_one(self) -> None:
        assert all(p <= 1.0 for p in holm_adjust([0.4, 0.5, 0.6, 0.7]))


class TestSrm:
    def test_balanced_split_is_not_flagged(self) -> None:
        result = srm_check([500, 500], [1.0, 1.0])
        assert result["chi2"] == pytest.approx(0.0, abs=1e-12)
        assert result["imbalanced"] is False

    def test_damaged_splitter_is_flagged(self) -> None:
        result = srm_check([900, 100], [1.0, 1.0])
        assert result["p_value"] < 1e-20
        assert result["imbalanced"] is True

    def test_matches_known_chi_square_for_a_mild_imbalance(self) -> None:
        result = srm_check([20206, 19794], [1.0, 1.0])
        assert result["chi2"] == pytest.approx(4.2436, abs=1e-4)
        assert result["p_value"] == pytest.approx(chi2_sf(result["chi2"], 1), rel=1e-12)

    def test_no_units_is_not_flagged(self) -> None:
        assert srm_check([0, 0], [0.5, 0.5])["imbalanced"] is False
