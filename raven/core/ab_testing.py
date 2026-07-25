from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ExperimentVariant:
    name: str
    weight: float
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentEvent:
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
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ABTestEngine:
    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._events: list[ExperimentEvent] = []

    def create_experiment(
        self, name: str, description: str, variants: list[dict[str, Any]], metric_name: str = "conversion"
    ) -> Experiment:
        exp = Experiment(
            id=uuid4().hex[:12],
            name=name,
            description=description,
            variants=[
                ExperimentVariant(name=v["name"], weight=v.get("weight", 1.0), config=v.get("config", {}))
                for v in variants
            ],
            metric_name=metric_name,
        )
        self._experiments[exp.id] = exp
        return exp

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self) -> list[Experiment]:
        return list(self._experiments.values())

    def update_experiment(self, experiment_id: str, **kwargs: Any) -> Experiment | None:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return None
        for key, value in kwargs.items():
            if hasattr(exp, key):
                if key == "variants":
                    setattr(
                        exp,
                        key,
                        [
                            ExperimentVariant(name=v["name"], weight=v.get("weight", 1.0), config=v.get("config", {}))
                            for v in value
                        ],
                    )
                else:
                    setattr(exp, key, value)
        exp.updated_at = time.time()
        return exp

    def delete_experiment(self, experiment_id: str) -> bool:
        return self._experiments.pop(experiment_id, None) is not None

    def start_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="running")

    def pause_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="paused")

    def complete_experiment(self, experiment_id: str) -> Experiment | None:
        return self.update_experiment(experiment_id, status="completed")

    def assign_variant(self, experiment_id: str, user_id: str = "") -> str | None:
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != "running":
            return None
        total_weight = sum(v.weight for v in exp.variants)
        if total_weight <= 0:
            return exp.variants[0].name if exp.variants else None
        import hashlib

        key = f"{experiment_id}:{user_id or uuid4().hex}"
        h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        r = (h % 10000) / 10000 * total_weight
        cumulative = 0.0
        for v in exp.variants:
            cumulative += v.weight
            if r <= cumulative:
                return v.name
        return exp.variants[-1].name if exp.variants else None

    def record_event(
        self, experiment_id: str, variant: str, metric_name: str, value: float = 1.0, user_id: str = ""
    ) -> None:
        self._events.append(ExperimentEvent(variant=variant, metric_name=metric_name, value=value, user_id=user_id))

    def get_results(self, experiment_id: str) -> dict[str, Any] | None:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return None
        variants = {v.name: {"events": 0, "total_value": 0.0, "count": 0} for v in exp.variants}
        for ev in self._events:
            if ev.metric_name == exp.metric_name and ev.variant in variants:
                variants[ev.variant]["events"] += 1
                variants[ev.variant]["total_value"] += ev.value
                variants[ev.variant]["count"] += 1

        result_variants: list[dict[str, Any]] = []
        for v in exp.variants:
            data = variants[v.name]
            result_variants.append(
                {
                    "name": v.name,
                    "weight": v.weight,
                    "config": v.config,
                    "events": data["events"],
                    "total_value": round(data["total_value"], 4),
                    "avg_value": round(data["total_value"] / data["count"], 4) if data["count"] > 0 else 0,
                    "sample_count": data["count"],
                }
            )

        control = next(
            (r for r in result_variants if r["name"] == exp.variants[0].name),
            result_variants[0] if result_variants else None,
        )
        for r in result_variants:
            if control and control["sample_count"] > 0 and r["sample_count"] > 0:
                r["lift"] = (
                    round((r["avg_value"] - control["avg_value"]) / control["avg_value"] * 100, 2)
                    if control["avg_value"] != 0
                    else 0
                )
            else:
                r["lift"] = 0

        significance = self._calculate_significance(result_variants) if len(result_variants) >= 2 else 0

        return {
            "experiment_id": exp.id,
            "name": exp.name,
            "status": exp.status,
            "metric": exp.metric_name,
            "variants": result_variants,
            "significance": round(significance, 4),
            "significant": significance >= 0.95,
            "total_events": sum(r["events"] for r in result_variants),
        }

    def _calculate_significance(self, variants: list[dict[str, Any]]) -> float:
        if len(variants) < 2:
            return 0.0
        control = variants[0]
        treatment = variants[1]
        if control["sample_count"] < 5 or treatment["sample_count"] < 5:
            return 0.0
        p1 = control["avg_value"]
        p2 = treatment["avg_value"]
        n1 = control["sample_count"]
        n2 = treatment["sample_count"]
        p_pool = (p1 * n1 + p2 * n2) / (n1 + n2) if (n1 + n2) > 0 else 0
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if p_pool * (1 - p_pool) > 0 else 1
        if se == 0:
            return 0.0
        z = abs(p2 - p1) / se
        p_value = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return 1 - 2 * (1 - p_value) if p_value > 0.5 else 2 * p_value


_engine = ABTestEngine()
