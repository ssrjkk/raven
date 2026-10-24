from __future__ import annotations

import math
from typing import Any

# Student t and chi-square need the regularized incomplete beta and the regularized incomplete
# gamma. Neither is in the standard library and scipy is not a dependency of this project, so both
# are implemented here from the Numerical Recipes continued fractions, and pinned against textbook
# values in tests/core/test_ab_stats.py.

_EPS = 3e-12
_FP_MIN = 1e-300
_MAX_ITER = 300


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FP_MIN:
        d = _FP_MIN
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FP_MIN:
            d = _FP_MIN
        c = 1.0 + aa / c
        if abs(c) < _FP_MIN:
            c = _FP_MIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FP_MIN:
            d = _FP_MIN
        c = 1.0 + aa / c
        if abs(c) < _FP_MIN:
            c = _FP_MIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value of |t| under Student t with `df` degrees of freedom."""
    if df <= 0:
        return 1.0
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def _gamma_p(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) by series."""
    term = 1.0 / a
    total = term
    for n in range(1, _MAX_ITER * 2):
        term *= x / (a + n)
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) by continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FP_MIN
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FP_MIN:
            d = _FP_MIN
        c = b + an / c
        if abs(c) < _FP_MIN:
            c = _FP_MIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """P(chi-square with `df` degrees of freedom > x)."""
    if x <= 0.0:
        return 1.0
    a, half_x = df / 2.0, x / 2.0
    return _gamma_q(a, half_x) if half_x > a + 1.0 else 1.0 - _gamma_p(a, half_x)


def mean_and_variance(values: list[float]) -> tuple[float, float, int]:
    """Sample mean, sample variance (n-1 denominator) and n."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0, n
    return mean, sum((v - mean) ** 2 for v in values) / (n - 1), n


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def permutation_test(control: list[float], treatment: list[float]) -> float | None:
    """Exact randomization p-value when both arms are constant with different means.

    With every control value equal to `a` and every treatment value equal to `b`, the pooled
    multiset has two distinct values, so re-labelling units is a hypergeometric draw: the number of
    `b` values that land in the control group. That makes the permutation distribution exact and
    cheap, which is what the degenerate Welch case needs instead of an invented p-value.
    Returns None when the values are not of this shape.
    """
    if not control or not treatment:
        return None
    a, b = control[0], treatment[0]
    if any(v != a for v in control) or any(v != b for v in treatment):
        return None
    if a == b:
        return 1.0
    n_c, n_t = len(control), len(treatment)
    n_b, total = n_t, n_c + n_t
    observed = abs(b - a)
    hit = 0.0
    # P(exactly k of the b-valued units land in the control group) under re-labelling
    for k in range(min(n_c, n_b) + 1):
        if n_c - k > total - n_b:
            continue
        log_p = _log_choose(n_b, k) + _log_choose(total - n_b, n_c - k) - _log_choose(total, n_c)
        if log_p < -745:
            continue
        diff = abs(((b * k + a * (n_c - k)) / n_c) - ((b * (n_b - k) + a * (total - n_b - (n_c - k))) / n_t))
        if diff >= observed - 1e-12:
            hit += math.exp(log_p)
    return min(1.0, hit)


def welch_test(
    control: list[float], treatment: list[float], alpha: float = 0.05
) -> dict[str, Any]:
    """Welch's t-test on per-unit values: unequal variances, no pooled-variance assumption."""
    mean_c, var_c, n_c = mean_and_variance(control)
    mean_t, var_t, n_t = mean_and_variance(treatment)
    result: dict[str, Any] = {
        "n_control": n_c,
        "n_treatment": n_t,
        "mean_control": mean_c,
        "mean_treatment": mean_t,
        "diff": mean_t - mean_c,
        "p_value": 1.0,
        "df": 0.0,
        "ci_low": mean_t - mean_c,
        "ci_high": mean_t - mean_c,
    }
    if n_c < 2 or n_t < 2:
        result["warning"] = "fewer than 2 units in an arm"
        return result
    se_squared = var_c / n_c + var_t / n_t
    if se_squared <= 0:
        # zero within-arm variance: the t-statistic is 0/0. If the two constants differ an exact
        # randomization test applies; if they are equal there is nothing to distinguish the arms by.
        permuted = permutation_test(control, treatment)
        result["p_value"] = permuted if permuted is not None else 1.0
        result["warning"] = (
            "zero variance within each arm: exact randomization test used"
            if permuted is not None and permuted < 1.0
            else "zero variance in both arms"
        )
        return result
    se = math.sqrt(se_squared)
    t_stat = (mean_t - mean_c) / se
    df = se_squared**2 / ((var_c / n_c) ** 2 / (n_c - 1) + (var_t / n_t) ** 2 / (n_t - 1))
    z = _z_critical(alpha, df)
    result["p_value"] = t_two_sided_p(t_stat, df)
    result["df"] = df
    result["ci_low"] = (mean_t - mean_c) - z * se
    result["ci_high"] = (mean_t - mean_c) + z * se
    return result


def _z_critical(alpha: float, df: float) -> float:
    """Two-sided critical value for `df` degrees of freedom, found by bisection on the p-function."""
    lo, hi = 0.0, 200.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        # t_two_sided_p decreases in t, so a p above the target means the bracket is still too low
        if t_two_sided_p(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def two_proportion_test(
    control_successes: int, control_units: int, treatment_successes: int, treatment_units: int,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Two-proportion z-test on per-unit outcomes.

    The statistic uses the pooled standard error (that is the null hypothesis being tested); the
    interval uses Newcombe's method, because the Wald interval collapses to zero width when an arm
    sits at exactly 0 or 100 percent -- which is the common early-experiment case.
    """
    p_c = control_successes / control_units if control_units else 0.0
    p_t = treatment_successes / treatment_units if treatment_units else 0.0
    result: dict[str, Any] = {
        "n_control": control_units,
        "n_treatment": treatment_units,
        "mean_control": p_c,
        "mean_treatment": p_t,
        "diff": p_t - p_c,
        "p_value": 1.0,
        "df": None,
        "ci_low": 0.0,
        "ci_high": 0.0,
    }
    if control_units < 2 or treatment_units < 2:
        result["warning"] = "fewer than 2 units in an arm"
        return result
    total_units = control_units + treatment_units
    p_pool = (control_successes + treatment_successes) / total_units
    if p_pool in (0.0, 1.0):
        # every unit in both arms gave the same answer: the null and the alternative are identical,
        # so there is no evidence either way. This is the case the old code turned into 1.0 confidence
        result["warning"] = "every unit in both arms has the same outcome"
        return result
    se_pooled = math.sqrt(p_pool * (1 - p_pool) * (1 / control_units + 1 / treatment_units))
    z_stat = (p_t - p_c) / se_pooled
    result["p_value"] = _normal_two_sided_p(z_stat)
    lo_c, hi_c = wilson_interval(control_successes, control_units, alpha)
    lo_t, hi_t = wilson_interval(treatment_successes, treatment_units, alpha)
    # Newcombe method 10: combine each arm's own Wilson interval, treatment first
    lower = (p_t - p_c) - math.sqrt((p_t - lo_t) ** 2 + (hi_c - p_c) ** 2)
    upper = (p_t - p_c) + math.sqrt((hi_t - p_t) ** 2 + (p_c - lo_c) ** 2)
    result["ci_low"] = max(-1.0, lower)
    result["ci_high"] = min(1.0, upper)
    return result


def _normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def _normal_critical(alpha: float) -> float:
    lo, hi = 0.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _normal_two_sided_p(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def wilson_interval(successes: int, units: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a proportion; the normal interval miscovers badly at small n."""
    if units <= 0:
        return 0.0, 1.0
    z = _normal_critical(alpha)
    ph = successes / units
    denom = 1.0 + z * z / units
    centre = (ph + z * z / (2 * units)) / denom
    width = z * math.sqrt(ph * (1 - ph) / units + z * z / (4 * units * units)) / denom
    return max(0.0, centre - width), min(1.0, centre + width)


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values, in the order given.

    Adjusted values are forced non-decreasing along the sorted order; without that step-down the
    result is not a valid Holm adjustment.
    """
    k = len(p_values)
    if k == 0:
        return []
    adjusted: list[float] = [0.0] * k
    running = 0.0
    for rank, idx in enumerate(sorted(range(k), key=lambda i: p_values[i])):
        running = max(running, (k - rank) * p_values[idx])
        adjusted[idx] = min(1.0, running)
    return adjusted


def srm_check(unit_counts: list[int], weights: list[float]) -> dict[str, Any]:
    """Sample-ratio-mismatch: is the observed traffic split compatible with the intended weights?

    A broken splitter (or a variant that silently never gets assigned) invalidates every comparison
    downstream, so this is reported next to the p-values rather than hidden.
    """
    total = sum(unit_counts)
    weight_sum = sum(weights)
    if total == 0 or weight_sum <= 0 or len(unit_counts) != len(weights):
        return {"chi2": 0.0, "p_value": 1.0, "imbalanced": False, "expected": []}
    expected = [total * w / weight_sum for w in weights]
    chi2 = sum((o - e) ** 2 / e for o, e in zip(unit_counts, expected, strict=True) if e > 0)
    p_value = chi2_sf(chi2, len(unit_counts) - 1)
    return {"chi2": chi2, "p_value": p_value, "imbalanced": p_value < 0.001, "expected": expected}
