from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.ab_testing_api as ab_api
from raven.core.ab_testing_api import create_ab_testing_router


@pytest.fixture()
def mock_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_engine: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    original = ab_api._engine
    ab_api._engine = mock_engine
    try:
        app.include_router(create_ab_testing_router())
        yield TestClient(app)
    finally:
        ab_api._engine = original


def test_create_experiment(client: TestClient, mock_engine: MagicMock) -> None:
    exp = MagicMock()
    exp.id = "e1"
    exp.name = "test"
    exp.status = "draft"
    v1 = MagicMock(name="a", weight=0.5)
    v2 = MagicMock(name="b", weight=0.5)
    exp.variants = [v1, v2]
    exp.metric_name = "conversion"
    mock_engine.create_experiment.return_value = exp

    resp = client.post(
        "/api/ab/experiments",
        json={"name": "test", "description": "desc", "variants_json": '[{"name":"a"},{"name":"b"}]'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "e1"


def test_create_experiment_invalid_json(client: TestClient) -> None:
    resp = client.post(
        "/api/ab/experiments",
        json={"name": "test", "description": "desc", "variants_json": "not json"},
    )
    assert resp.status_code == 400


def test_create_experiment_too_few_variants(client: TestClient) -> None:
    resp = client.post(
        "/api/ab/experiments",
        json={"name": "test", "description": "desc", "variants_json": '[{"name":"a"}]'},
    )
    assert resp.status_code == 400


def test_list_experiments(client: TestClient, mock_engine: MagicMock) -> None:
    e = MagicMock()
    e.id = "e1"
    e.name = "test"
    e.status = "running"
    e.variants = []
    e.metric_name = "conversion"
    e.created_at = "2026-01-01"
    mock_engine.list_experiments.return_value = [e]

    resp = client.get("/api/ab/experiments")
    assert resp.status_code == 200
    assert len(resp.json()["experiments"]) == 1


def test_get_experiment(client: TestClient, mock_engine: MagicMock) -> None:
    exp = MagicMock()
    exp.id = "e1"
    exp.name = "test"
    exp.description = "desc"
    exp.status = "running"
    exp.variants = []
    exp.metric_name = "conversion"
    exp.created_at = "2026-01-01"
    exp.updated_at = "2026-01-02"
    mock_engine.get_experiment.return_value = exp

    resp = client.get("/api/ab/experiments/e1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "e1"


def test_get_experiment_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.get_experiment.return_value = None
    resp = client.get("/api/ab/experiments/unknown")
    assert resp.status_code == 404


def test_update_status(client: TestClient, mock_engine: MagicMock) -> None:
    exp = MagicMock()
    exp.id = "e1"
    exp.status = "running"
    mock_engine.start_experiment.return_value = exp

    resp = client.post("/api/ab/experiments/e1/status", json={"status": "running"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_update_status_invalid(client: TestClient) -> None:
    resp = client.post("/api/ab/experiments/e1/status", json={"status": "invalid"})
    assert resp.status_code == 400


def test_update_status_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.start_experiment.return_value = None
    resp = client.post("/api/ab/experiments/e1/status", json={"status": "running"})
    assert resp.status_code == 404


def test_delete_experiment(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.delete_experiment.return_value = True
    resp = client.delete("/api/ab/experiments/e1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_delete_experiment_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.delete_experiment.return_value = False
    resp = client.delete("/api/ab/experiments/unknown")
    assert resp.status_code == 404


def test_assign_variant(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.assign_variant.return_value = "a"
    resp = client.post("/api/ab/experiments/e1/assign", json={"user_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["variant"] == "a"


def test_assign_variant_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.assign_variant.return_value = None
    resp = client.post("/api/ab/experiments/e1/assign")
    assert resp.status_code == 400


def test_record_event(client: TestClient, mock_engine: MagicMock) -> None:
    exp = MagicMock()
    mock_engine.get_experiment.return_value = exp
    resp = client.post(
        "/api/ab/experiments/e1/record",
        json={"variant": "a", "metric_name": "conversion", "value": 1.0},
    )
    assert resp.status_code == 200


def test_record_event_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.get_experiment.return_value = None
    resp = client.post("/api/ab/experiments/e1/record", json={"variant": "a"})
    assert resp.status_code == 404


def test_get_results(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.get_results.return_value = {"variant_a": {"conversions": 10}}
    resp = client.get("/api/ab/experiments/e1/results")
    assert resp.status_code == 200


def test_get_results_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    mock_engine.get_results.return_value = None
    resp = client.get("/api/ab/experiments/unknown/results")
    assert resp.status_code == 404
