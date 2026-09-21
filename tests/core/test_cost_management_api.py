from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.cost_management_api as cost_mod
from raven.core.cost_management_api import create_cost_management_router


@pytest.fixture()
def mock_cost() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_cost: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(create_cost_management_router())
    original = cost_mod._cost
    cost_mod._cost = mock_cost
    try:
        yield TestClient(app)
    finally:
        cost_mod._cost = original


def test_record_usage(client: TestClient, mock_cost: MagicMock) -> None:
    rec = MagicMock()
    rec.id = "u1"
    rec.model = "gpt-4"
    rec.input_tokens = 100
    rec.output_tokens = 50
    rec.cost = 0.01
    rec.duration_ms = 200.0
    mock_cost.record_usage.return_value = rec

    resp = client.post(
        "/api/cost/usage",
        json={"model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "u1"
    assert data["model"] == "gpt-4"


def test_get_recent_usage(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.get_recent_usage.return_value = [{"id": "u1", "model": "gpt-4"}]
    resp = client.get("/api/cost/usage/recent")
    assert resp.status_code == 200
    assert "usage" in resp.json()


def test_get_summary(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.get_usage_summary.return_value = {"total_cost": 1.5, "total_tokens": 1000}
    resp = client.get("/api/cost/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 1.5


def test_get_pricing(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.get_model_pricing.return_value = {"gpt-4": {"input": 0.03, "output": 0.06}}
    resp = client.get("/api/cost/pricing")
    assert resp.status_code == 200
    assert "pricing" in resp.json()


def test_set_pricing(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.set_model_pricing.return_value = None
    resp = client.put("/api/cost/pricing/gpt-4", json={"input_per_1k": 0.03, "output_per_1k": 0.06})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_create_budget(client: TestClient, mock_cost: MagicMock) -> None:
    budget = MagicMock()
    budget.id = "b1"
    budget.name = "test"
    budget.daily_limit = 10.0
    budget.monthly_limit = 100.0
    mock_cost.set_budget.return_value = budget

    resp = client.post("/api/cost/budgets", json={"name": "test", "daily_limit": 10.0, "monthly_limit": 100.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "b1"


def test_list_budgets(client: TestClient, mock_cost: MagicMock) -> None:
    b = MagicMock()
    b.id = "b1"
    b.name = "test"
    b.daily_limit = 10.0
    b.monthly_limit = 100.0
    b.current_daily = 5.0
    b.current_monthly = 50.0
    mock_cost.get_budgets.return_value = [b]

    resp = client.get("/api/cost/budgets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["budgets"]) == 1


def test_delete_budget(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.delete_budget.return_value = True
    resp = client.delete("/api/cost/budgets/b1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_delete_budget_not_found(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.delete_budget.return_value = False
    resp = client.delete("/api/cost/budgets/unknown")
    assert resp.status_code == 404


def test_cost_check(client: TestClient, mock_cost: MagicMock) -> None:
    mock_cost.get_total_cost.return_value = 50.0
    mock_cost.get_daily_cost.return_value = 10.0
    mock_cost.get_monthly_cost.return_value = 50.0
    mock_cost.is_budget_exceeded.return_value = False

    resp = client.get("/api/cost/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 50.0
    assert data["budget_exceeded"] is False
