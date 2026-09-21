from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.chaos_api as chaos_mod
from raven.core.chaos_api import create_chaos_router


@pytest.fixture()
def mock_ce() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_ce: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    original = chaos_mod._ce
    chaos_mod._ce = mock_ce
    try:
        app.include_router(create_chaos_router())
        yield TestClient(app)
    finally:
        chaos_mod._ce = original


def test_inject(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.inject = AsyncMock(return_value={"fault_id": "f1", "status": "active"})
    resp = client.post("/api/chaos/inject", json={"fault_type": "network_latency", "target": "api", "duration_sec": 30.0})
    assert resp.status_code == 200


def test_inject_invalid_fault_type(client: TestClient) -> None:
    resp = client.post("/api/chaos/inject", json={"fault_type": "nonexistent_type"})
    assert resp.status_code == 400


def test_recover(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.recover = AsyncMock(return_value={"fault_id": "f1", "status": "recovered"})
    resp = client.post("/api/chaos/recover", json={"fault_id": "f1"})
    assert resp.status_code == 200


def test_recover_not_found(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.recover = AsyncMock(return_value=None)
    resp = client.post("/api/chaos/recover", json={"fault_id": "unknown"})
    assert resp.status_code == 404


def test_recover_all(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.recover_all = AsyncMock(return_value=["f1", "f2"])
    resp = client.post("/api/chaos/recover_all")
    assert resp.status_code == 200
    assert resp.json()["recovered"] == 2


def test_list_active(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.active_faults = {"f1": {"fault_id": "f1", "type": "network_latency"}}
    resp = client.get("/api/chaos/active")
    assert resp.status_code == 200
    assert len(resp.json()["active"]) == 1


def test_list_history(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.injector.get_history.return_value = [{"fault_id": "f1"}]
    resp = client.get("/api/chaos/history")
    assert resp.status_code == 200
    assert len(resp.json()["history"]) == 1


def test_run_experiment(client: TestClient, mock_ce: MagicMock) -> None:
    result = MagicMock()
    result.experiment_id = "exp1"
    result.status = MagicMock()
    result.status.value = "completed"
    result.resilience_score = 0.85
    result.hypothesis_validated = True
    result.faults_injected = [1, 2]
    result.faults_recovered = [1, 2]
    mock_ce.run_experiment = AsyncMock(return_value=result)

    resp = client.post(
        "/api/chaos/experiments",
        json={"name": "test", "faults_json": '[{"fault_type": "network_latency"}]', "hypothesis": "test hyp"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["experiment_id"] == "exp1"


def test_run_experiment_invalid_json(client: TestClient) -> None:
    resp = client.post("/api/chaos/experiments", json={"name": "test", "faults_json": "bad json"})
    assert resp.status_code == 400


def test_list_experiments(client: TestClient, mock_ce: MagicMock) -> None:
    e = MagicMock()
    e.config.name = "test-exp"
    mock_ce.list_experiments.return_value = [e]
    resp = client.get("/api/chaos/experiments")
    assert resp.status_code == 200
    assert "test-exp" in resp.json()["experiments"]


def test_get_experiment(client: TestClient, mock_ce: MagicMock) -> None:
    result = MagicMock()
    result.experiment_id = "exp1"
    result.config.name = "test"
    result.status = MagicMock()
    result.status.value = "completed"
    mock_ce.get_experiment.return_value = result

    resp = client.get("/api/chaos/experiments/exp1")
    assert resp.status_code == 200


def test_get_experiment_not_found(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.get_experiment.return_value = None
    resp = client.get("/api/chaos/experiments/unknown")
    assert resp.status_code == 404


def test_experiment_report(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.generate_report.return_value = {"summary": "ok"}
    resp = client.get("/api/chaos/experiments/exp1/report")
    assert resp.status_code == 200


def test_experiment_report_not_found(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.generate_report.side_effect = ValueError("not found")
    resp = client.get("/api/chaos/experiments/unknown/report")
    assert resp.status_code == 404


def test_resilience_summary(client: TestClient, mock_ce: MagicMock) -> None:
    mock_ce.get_resilience_summary.return_value = {"score": 0.9}
    resp = client.get("/api/chaos/resilience/summary")
    assert resp.status_code == 200
    assert resp.json()["score"] == 0.9
