from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from raven.core.ab_stats import holm_adjust, srm_check, two_proportion_test, welch_test

METRIC_TYPES = ("rate", "mean")

# A split smaller than this cannot be represented by the assignment buckets, so such a weight would
# silently produce an arm that never receives traffic.
_MIN_WEIGHT_SHARE = 1e-4
_ASSIGNMENT_BUCKETS = 1_000_000


@dataclass
class ExperimentVariant:
    name: str
    weight: float = 1.0
    config: dict[str, Any] = field(default_factory=dict)
    is_control: bool = False


@dataclass
class ExperimentEvent:
    experiment_id: str
    variant: str
    metric_name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    user_id: str = ""


@dataclass
class Experiment:
    id: str
    name: str
    description: str
    variants: list[ExperimentVariant]
    status: str = "draft"  # draft | running | paused | completed
    metric_name: str = "conversion"
    metric_type: str = "rate"  # rate (per-unit outcome) | mean (per-unit continuous value)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def control(self) -> ExperimentVariant:
        return next(v for v in self.variants if v.is_control)


class ABTestEngine:
    """A/B experiment registry and analyzer.

    Events belong to one experiment and are aggregated to the unit of randomization before any test
    is computed: six events from one user are n=1, not n=6.
    """

    def __init__(self, max_events_per_experiment: int = 1_000_000) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._events: dict[str, list[ExperimentEvent]] = {}
        self._dropped: dict[str, int] = {}
        self._max_events = max_events_per_experiment

    # --- experiment lifecycle ---

    def create_experiment(
        self,
        name: str,
        description: str,
        variants: list[dict[str, Any]],
        metric_name: str = "conversion",
        metric_type: str = "rate",
    ) -> Experiment:
        parsed = self._parse_variants(variants)
        if metric_type not in METRIC_TYPES:
            msg = f"metric_type must be one of {METRIC_TYPES}, got {metric_type!r}"
            raise ValueError(msg)
        exp = Experiment(
            id=uuid4().hex[:12],
            name=name,
            description=description,
            variants=parsed,
            metric_name=metric_name,
            metric_type=metric_type,
        )
        self._experiments[exp.id] = exp
        self._events[exp.id] = []
        self._dropped[exp.id] = 0
        return exp

    @staticmethod
    def _parse_variants(variants: list[dict[str, Any]]) -> list[ExperimentVariant]:
        if len(variants) < 2:
            msg = f"an experiment needs at least 2 variants, got {len(variants)}"
            raise ValueError(msg)
        parsed: list[ExperimentVariant] = []
        for raw in variants:
            name = str(raw.get("name", "")).strip()
            if not name:
                msg = "every variant needs a non-empty name"
                raise ValueError(msg)
            if any(p.name == name for p in parsed):
                msg = f"duplicate variant name {name!r}"
                raise ValueError(msg)
            weight = raw.get("weight", 1.0)
            if not isinstance(weight, int | float) or isinstance(weight, bool) or not math.isfinite(float(weight)):
                msg = f"variant {name!r} needs a finite numeric weight, got {weight!r}"
                raise ValueError(msg)
            if float(weight) <= 0:
                msg = f"variant {name!r} needs a weight > 0 (a zero-weight arm still gets traffic)"
                raise ValueError(msg)
            parsed.append(
                ExperimentVariant(
                    name=name,
                    weight=float(weight),
                    config=dict(raw.get("config") or {}),
                    is_control=bool(raw.get("is_control", False)),
                )
            )
        total = sum(p.weight for p in parsed)
        too_small = [p.name for p in parsed if p.weight / total < _MIN_WEIGHT_SHARE]
        if too_small:
            msg = (
                f"variant(s) {too_small} get less than {_MIN_WEIGHT_SHARE * 100:.2f}% of the traffic share; "
                "the splitter cannot represent them and they would never be assigned"
            )
            raise ValueError(msg)
        controls = [p for p in parsed if p.is_control]
        if len(controls) > 1:
            msg = f"only one variant may be the control, got {[c.name for c in controls]}"
            raise ValueError(msg)
        if not controls:
            parsed[0].is_control = True
        return parsed

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self) -> list[Experiment]:
        return list(self._experiments.values())

    def update_experiment(self, experiment_id: str, **kwargs: Any) -> Experiment | None:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return None
        for key, value in kwargs.items():
            if key == "variants":
                exp.variants = self._parse_variants(list(value))
            elif key == "metric_type":
                if value not in METRIC_TYPES:
                    msg = f"metric_type must be one of {METRIC_TYPES}, got {value!r}"
                    raise ValueError(msg)
                exp.metric_type = str(value)
            elif hasattr(exp, key):
                setattr(exp, key, value)
        exp.updated_at = time.time()
        return exp

    def delete_experiment(self, experiment_id: str) -> bool:
        self._events.pop(experiment_id, None)
        self._dropped.pop(experiment_id, None)
        return self._experiments.pop(experiment_id, None) is not None

    def start_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="running")

    def pause_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="paused")

    def complete_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="completed")

    # --- assignment and recording ---

    def assign_variant(self, experiment_id: str, user_id: str = "") -> str | None:
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != "running":
            return None
        if not user_id:
            msg = (
                "assign_variant needs a subject id: without one the same caller cannot be kept in "
                "the same arm, and their events are not attributable to a unit of randomization"
            )
            raise ValueError(msg)
        key = f"{experiment_id}:{user_id}".encode()
        position = (int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % _ASSIGNMENT_BUCKETS) / _ASSIGNMENT_BUCKETS
        total = sum(v.weight for v in exp.variants)
        cumulative = 0.0
        for v in exp.variants:
            cumulative += v.weight / total
            if position < cumulative:
                return v.name
        return exp.variants[-1].name

    def record_event(
        self, experiment_id: str, variant: str, metric_name: str, value: float = 1.0, user_id: str = ""
    ) -> ExperimentEvent:
        exp = self._experiments.get(experiment_id)
        if not exp:
            msg = f"experiment {experiment_id!r} not found"
            raise KeyError(msg)
        if variant not in {v.name for v in exp.variants}:
            known = [v.name for v in exp.variants]
            msg = f"variant {variant!r} is not part of experiment {experiment_id}; known variants: {known}"
            raise ValueError(msg)
        if metric_name != exp.metric_name:
            msg = f"experiment {experiment_id} measures {exp.metric_name!r}, not {metric_name!r}"
            raise ValueError(msg)
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
            msg = f"metric value must be a finite number, got {value!r}"
            raise ValueError(msg)
        numeric = float(value)
        if exp.metric_type == "rate" and not 0.0 <= numeric <= 1.0:
            msg = f"metric_type 'rate' requires a value in [0, 1], got {numeric!r}"
            raise ValueError(msg)

        stored = self._events.setdefault(experiment_id, [])
        if len(stored) >= self._max_events:
            self._dropped[experiment_id] = self._dropped.get(experiment_id, 0) + 1
            msg = f"experiment {experiment_id} reached its {self._max_events} event cap"
            raise RuntimeError(msg)
        event = ExperimentEvent(
            experiment_id=experiment_id,
            variant=variant,
            metric_name=metric_name,
            value=numeric,
            user_id=user_id,
        )
        stored.append(event)
        return event

    # --- analysis ---

    def get_results(self, experiment_id: str) -> dict[str, Any] | None:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return None
        known = {v.name for v in exp.variants}
        stored = self._events.get(experiment_id, [])
        # a variant removed by update_experiment leaves events behind; they are reported, not dropped
        orphaned = [e for e in stored if e.variant not in known]
        events = [e for e in stored if e.variant in known and e.metric_name == exp.metric_name]

        per_variant_events: dict[str, list[ExperimentEvent]] = {v.name: [] for v in exp.variants}
        for e in events:
            per_variant_events[e.variant].append(e)

        units: dict[str, dict[str, list[float]]] = {v.name: {} for v in exp.variants}
        unattributed: dict[str, int] = {v.name: 0 for v in exp.variants}
        for v in exp.variants:
            for e in per_variant_events[v.name]:
                if e.user_id:
                    units[v.name].setdefault(e.user_id, []).append(e.value)
                else:
                    unattributed[v.name] += 1

        binary = exp.metric_type == "rate" and all(
            e.value in (0.0, 1.0) for v in exp.variants for e in per_variant_events[v.name]
        )
        per_unit: dict[str, list[float]] = {}
        for v in exp.variants:
            if binary:
                # funnel semantics: a user converted if any of their events converted
                per_unit[v.name] = [1.0 if max(vals, default=0.0) >= 0.5 else 0.0 for vals in units[v.name].values()]
            else:
                per_unit[v.name] = [sum(vals) / len(vals) for vals in units[v.name].values()]

        control_name = exp.control.name
        comparisons = self._compare(exp, per_unit, control_name, binary)

        variant_rows: list[dict[str, Any]] = []
        for v in exp.variants:
            values = per_unit[v.name]
            total = sum(e.value for e in per_variant_events[v.name])
            count = len(per_variant_events[v.name])
            row: dict[str, Any] = {
                "name": v.name,
                "weight": v.weight,
                "config": v.config,
                "is_control": v.is_control,
                "events": count,
                "sample_count": len(values),
                "unattributed_events": unattributed[v.name],
                "avg_value": round(total / count, 6) if count else 0.0,
                "unit_avg": round(sum(values) / len(values), 6) if values else 0.0,
            }
            match = next((c for c in comparisons if c["variant"] == v.name), {}) if not v.is_control else {}
            row["lift"] = match.get("lift")
            row["p_value"] = match.get("p_value")
            row["p_adjusted"] = match.get("p_adjusted")
            row["significant"] = bool(match.get("significant"))
            variant_rows.append(row)

        unit_counts = [len(per_unit[v.name]) for v in exp.variants]
        srm = srm_check(unit_counts, [v.weight for v in exp.variants])
        warnings = self._warnings(exp, comparisons, srm, unattributed, per_unit)
        if orphaned:
            warnings.append(
                f"{len(orphaned)} events recorded under variants that no longer exist in this "
                "experiment were excluded from the result"
            )

        return {
            "experiment_id": exp.id,
            "name": exp.name,
            "status": exp.status,
            "metric": exp.metric_name,
            "metric_type": exp.metric_type,
            "method": "two_proportion_z_on_units" if binary else "welch_t_on_unit_means",
            "alpha": 0.05,
            "multiplicity": "holm-bonferroni",
            "control": control_name,
            "variants": variant_rows,
            "comparisons": comparisons,
            "significant": any(c["significant"] for c in comparisons),
            "srm": {k: srm[k] for k in ("chi2", "p_value", "imbalanced")},
            "total_events": len(events),
            "events_stored": len(stored),
            "events_dropped": self._dropped.get(experiment_id, 0),
            "events_orphaned": len(orphaned),
            "events_unattributed": sum(unattributed.values()),
            "unit_counts": dict(zip([v.name for v in exp.variants], unit_counts, strict=True)),
            "warnings": warnings,
        }

    def _compare(
        self, exp: Experiment, per_unit: dict[str, list[float]], control_name: str, binary: bool
    ) -> list[dict[str, Any]]:
        control_values = per_unit[control_name]
        raw: list[dict[str, Any]] = []
        for v in exp.variants:
            if v.name == control_name:
                continue
            values = per_unit[v.name]
            if binary:
                stats = two_proportion_test(
                    int(sum(control_values)),
                    len(control_values),
                    int(sum(values)),
                    len(values),
                )
            else:
                stats = welch_test(control_values, values)
            mean_c = 0.0 if stats["mean_control"] is None else float(stats["mean_control"])
            mean_t = 0.0 if stats["mean_treatment"] is None else float(stats["mean_treatment"])
            ci_low = stats["ci_low"] if stats["ci_low"] is not None else 0.0
            ci_high = stats["ci_high"] if stats["ci_high"] is not None else 0.0
            raw.append(
                {
                    "variant": v.name,
                    "control": control_name,
                    "units": len(values),
                    "control_units": len(control_values),
                    "mean": round(mean_t, 6),
                    "control_mean": round(mean_c, 6),
                    "diff": round(mean_t - mean_c, 6),
                    "diff_ci_low": round(float(ci_low), 6),
                    "diff_ci_high": round(float(ci_high), 6),
                    # relative lift is undefined when the control baseline is zero
                    "lift": None if mean_c == 0 else round((mean_t - mean_c) / abs(mean_c) * 100, 4),
                    "p_value": 1.0 if stats["p_value"] is None else float(stats["p_value"]),
                    "test": "two_proportion_z" if binary else "welch_t",
                    "warning": stats.get("warning"),
                }
            )
        adjusted = holm_adjust([r["p_value"] for r in raw])
        for row, p_adj in zip(raw, adjusted, strict=True):
            row["p_adjusted"] = round(p_adj, 8)
            row["significant"] = p_adj < 0.05
        return raw

    @staticmethod
    def _warnings(
        exp: Experiment,
        comparisons: list[dict[str, Any]],
        srm: dict[str, Any],
        unattributed: dict[str, int],
        per_unit: dict[str, list[float]],
    ) -> list[str]:
        warnings: list[str] = []
        if srm.get("imbalanced"):
            warnings.append(
                f"sample ratio mismatch: observed unit split is incompatible with the configured "
                f"weights (chi2={srm['chi2']:.2f}, p={srm['p_value']:.2e})"
            )
        total_unattributed = sum(unattributed.values())
        if total_unattributed:
            warnings.append(
                f"{total_unattributed} events have no user_id and were excluded from the test: they "
                "cannot be attributed to a unit of randomization"
            )
        for row in comparisons:
            if row.get("warning"):
                warnings.append(f"{row['variant']} vs {row['control']}: {row['warning']}")
        if any(len(values) == 0 for values in per_unit.values()):
            empty = [v.name for v in exp.variants if not per_unit[v.name]]
            warnings.append(f"arm(s) {empty} have no measurable units")
        return warnings


_engine = ABTestEngine()
