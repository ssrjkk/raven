"""CostManager state: bounded detail ring, exact lifetime total, per-instance pricing."""

from __future__ import annotations

import time

import pytest

import raven.core.cost_management as cm
from raven.core.cost_management import CostManager, UsageRecord


def _record(costs: CostManager, model: str = "gpt-4o", tokens: int = 1000) -> UsageRecord:
    return costs.record_usage(model, tokens, tokens // 2)


def _stamp(costs: CostManager, record_id: str, timestamp: float) -> UsageRecord:
    record = UsageRecord(id=record_id, model="m", input_tokens=1, output_tokens=1,
                         cost=0.0, user_id="", channel="", session_id="", timestamp=timestamp)
    costs._records.append(record)
    return record


def test_lifetime_total_survives_the_detail_ring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm, "_RECORD_WINDOW", 4)
    costs = CostManager()
    for _ in range(10):
        _record(costs)

    assert len(costs._records) == 4
    assert costs.dropped_records == 6
    one_call = _record(CostManager()).cost
    assert costs.get_total_cost() == pytest.approx(one_call * 10)
    assert len(costs.get_recent_usage(limit=100)) == 4


def test_recent_usage_reports_newest_first() -> None:
    costs = CostManager()
    for record_id, timestamp in [("oldest", 100.0), ("middle", 200.0), ("newest", 300.0)]:
        _stamp(costs, record_id, timestamp)
    assert [r["id"] for r in costs.get_recent_usage(limit=2)] == ["newest", "middle"]
    assert [r.id for r in costs._records] == ["oldest", "middle", "newest"]


def test_pricing_override_is_per_instance() -> None:
    default = CostManager()
    tuned = CostManager()
    before = default.get_model_pricing()["gpt-4o"]["input_per_1k"]

    tuned.set_model_pricing("gpt-4o", 0.0, 0.0)

    assert default.get_model_pricing()["gpt-4o"]["input_per_1k"] == before
    assert cm.MODEL_PRICING["gpt-4o"]["input_per_1k"] == before
    assert _record(tuned).cost == 0.0
    assert _record(default).cost > 0.0


def test_records_since_applies_the_window() -> None:
    costs = CostManager()
    _record(costs)
    assert [r.model for r in costs.records_since(0.0)] == ["gpt-4o"]
    assert costs.records_since(time.time() + 3600) == []


def test_ring_keeps_the_recent_window_the_dashboards_read() -> None:
    costs = CostManager()
    for i in range(cm._RECORD_WINDOW + 5):
        _stamp(costs, str(i), 1000.0 + i)
    assert len(costs._records) == cm._RECORD_WINDOW
    assert costs._records[0].id == "5"          # the five oldest were pushed out
    assert costs.records_since(1000.5)[0].id == "5"
