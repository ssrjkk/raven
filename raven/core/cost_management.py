from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from itertools import islice
from typing import Any
from uuid import uuid4

MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    "gpt-4-turbo": {"input_per_1k": 0.01, "output_per_1k": 0.03},
    "gpt-3.5-turbo": {"input_per_1k": 0.001, "output_per_1k": 0.002},
    "claude-3-5-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "claude-3-haiku": {"input_per_1k": 0.00025, "output_per_1k": 0.00125},
    "claude-opus": {"input_per_1k": 0.015, "output_per_1k": 0.075},
    "gemini-1.5-pro": {"input_per_1k": 0.0035, "output_per_1k": 0.0105},
    "gemini-1.5-flash": {"input_per_1k": 0.000075, "output_per_1k": 0.0003},
    "llama-3-70b": {"input_per_1k": 0.00065, "output_per_1k": 0.00087},
    "llama-3-8b": {"input_per_1k": 0.00015, "output_per_1k": 0.0002},
    "mistral-large": {"input_per_1k": 0.002, "output_per_1k": 0.006},
    "mistral-7b": {"input_per_1k": 0.0001, "output_per_1k": 0.00015},
    "deepseek-coder": {"input_per_1k": 0.00014, "output_per_1k": 0.00028},
    "openrouter-auto": {"input_per_1k": 0.001, "output_per_1k": 0.003},
}

DEFAULT_PRICING = {"input_per_1k": 0.001, "output_per_1k": 0.002}

# Detail ring. Every LLM call used to append forever, so a gateway that had been up for weeks
# carried hundreds of thousands of records that only ever got scanned in full; the totals that
# matter are accumulated separately, so bounding the detail list cannot change a number anyone
# reads - it only bounds how far back the per-call drill-down reaches.
_RECORD_WINDOW = 10_000


@dataclass
class UsageRecord:
    id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    user_id: str
    channel: str
    session_id: str
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class BudgetLimit:
    id: str
    name: str
    daily_limit: float
    monthly_limit: float
    current_daily: float = 0.0
    current_monthly: float = 0.0
    reset_day: str = ""
    reset_month: str = ""


class CostManager:
    def __init__(self) -> None:
        self._records: deque[UsageRecord] = deque(maxlen=_RECORD_WINDOW)
        self._lifetime_cost = 0.0
        self._dropped_records = 0
        self._pricing: dict[str, dict[str, float]] = {m: dict(v) for m, v in MODEL_PRICING.items()}
        self._budgets: dict[str, BudgetLimit] = {}
        self._daily_usage: dict[str, float] = defaultdict(float)
        self._monthly_usage: dict[str, float] = defaultdict(float)
        self._last_reset_day = ""
        self._last_reset_month = ""

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        user_id: str = "",
        channel: str = "",
        session_id: str = "",
        duration_ms: float = 0.0,
    ) -> UsageRecord:
        pricing = self._pricing.get(model, DEFAULT_PRICING)
        cost = (input_tokens / 1000) * pricing["input_per_1k"] + (output_tokens / 1000) * pricing["output_per_1k"]
        rec = UsageRecord(
            id=uuid4().hex[:12],
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=round(cost, 6),
            user_id=user_id,
            channel=channel,
            session_id=session_id,
            duration_ms=duration_ms,
        )
        if len(self._records) == self._records.maxlen:
            self._dropped_records += 1
        self._records.append(rec)
        self._lifetime_cost += cost
        self._check_reset()
        self._daily_usage[model] += cost
        self._monthly_usage[model] += cost
        return rec

    def _check_reset(self) -> None:
        today = time.strftime("%Y-%m-%d")
        this_month = time.strftime("%Y-%m")
        if today != self._last_reset_day:
            self._daily_usage.clear()
            self._last_reset_day = today
        if this_month != self._last_reset_month:
            self._monthly_usage.clear()
            self._last_reset_month = this_month

    def get_model_pricing(self) -> dict[str, dict[str, float]]:
        # Overrides were written into the module-level MODEL_PRICING, so one PUT poisoned the
        # table for every other CostManager in the process and for later tests.
        return {m: dict(v) for m, v in self._pricing.items()}

    def set_model_pricing(self, model: str, input_per_1k: float, output_per_1k: float) -> None:
        self._pricing[model] = {"input_per_1k": input_per_1k, "output_per_1k": output_per_1k}

    def get_daily_cost(self, model: str | None = None) -> float:
        self._check_reset()
        if model:
            return self._daily_usage.get(model, 0.0)
        return sum(self._daily_usage.values())

    def get_monthly_cost(self, model: str | None = None) -> float:
        self._check_reset()
        if model:
            return self._monthly_usage.get(model, 0.0)
        return sum(self._monthly_usage.values())

    def get_total_cost(self) -> float:
        return self._lifetime_cost

    def records_since(self, cutoff: float) -> list[UsageRecord]:
        """Records still held in the detail ring that were logged at or after *cutoff*.

        Callers used to read ``_cost._records`` directly; that private list is now bounded, so
        the window is exposed here together with ``dropped_records``.
        """
        return [r for r in self._records if r.timestamp >= cutoff]

    @property
    def dropped_records(self) -> int:
        return self._dropped_records

    def get_usage_summary(self, hours: int = 24) -> dict[str, Any]:
        cutoff = time.time() - hours * 3600
        recent = [r for r in self._records if r.timestamp >= cutoff]
        by_model: dict[str, dict[str, float | int]] = {}
        total_cost = 0.0
        total_input = 0
        total_output = 0
        total_duration = 0.0
        for r in recent:
            total_cost += r.cost
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_duration += r.duration_ms
            if r.model not in by_model:
                by_model[r.model] = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0, "duration_ms": 0.0}
            by_model[r.model]["cost"] += r.cost
            by_model[r.model]["input_tokens"] += r.input_tokens
            by_model[r.model]["output_tokens"] += r.output_tokens
            by_model[r.model]["calls"] += 1
            by_model[r.model]["duration_ms"] += r.duration_ms

        return {
            "total_cost": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_calls": len(recent),
            "total_duration_ms": round(total_duration, 1),
            "by_model": {
                m: {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()} for m, d in by_model.items()
            },
            "daily_cost": round(self.get_daily_cost(), 4),
            "monthly_cost": round(self.get_monthly_cost(), 4),
        }

    def get_recent_usage(self, limit: int = 50) -> list[dict[str, Any]]:
        # The ring is already append-ordered, and it is scanned in full on every dashboard
        # poll: reversed()+islice gives the newest *limit* records without sorting.
        records = list(islice(reversed(self._records), max(0, limit)))
        return [
            {
                "id": r.id,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost": r.cost,
                "duration_ms": r.duration_ms,
                "user_id": r.user_id,
                "channel": r.channel,
                "session_id": r.session_id,
                "timestamp": r.timestamp,
            }
            for r in records
        ]

    def set_budget(self, name: str, daily_limit: float, monthly_limit: float) -> BudgetLimit:
        budget = BudgetLimit(
            id=uuid4().hex[:12],
            name=name,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
        )
        self._budgets[budget.id] = budget
        return budget

    def get_budgets(self) -> list[BudgetLimit]:
        self._check_reset()
        today = time.strftime("%Y-%m-%d")
        this_month = time.strftime("%Y-%m")
        for b in self._budgets.values():
            b.current_daily = self.get_daily_cost()
            b.current_monthly = self.get_monthly_cost()
            b.reset_day = today
            b.reset_month = this_month
        return list(self._budgets.values())

    def delete_budget(self, budget_id: str) -> bool:
        return self._budgets.pop(budget_id, None) is not None

    def is_budget_exceeded(self) -> bool:
        self._check_reset()
        for b in self._budgets.values():
            if b.daily_limit > 0 and self.get_daily_cost() >= b.daily_limit:
                return True
            if b.monthly_limit > 0 and self.get_monthly_cost() >= b.monthly_limit:
                return True
        return False


_cost = CostManager()
