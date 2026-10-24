from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.ab_testing_api as ab_api
from raven.core.ab_testing import ABTestEngine
from raven.core.ab_testing_api import create_ab_testing_router

VARIANTS = '[{"name":"Control","weight":1.0,"is_control":true},{"name":"Treatment","weight":1.0}]'


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine = ABTestEngine()
    original = ab_api._engine
    ab_api._engine = engine
    try:
        app = FastAPI()
        app.include_router(create_ab_testing_router())
        yield TestClient(app)
    finally:
        ab_api._engine = original


def create(client: TestClient, **overrides: Any) -> str:
    payload = {"name": "exp", "description": "desc", "variants_json": VARIANTS, "metric_name": "conversion"}
    payload.update(overrides)
    resp = client.post("/api/ab/experiments", json=payload)
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


class TestCreate:
    def test_created_experiment_reports_the_control_and_metric_type(self, client: TestClient) -> None:
        payload = {
            "name": "exp",
            "description": "desc",
            "variants_json": VARIANTS,
            "metric_name": "latency",
            "metric_type": "mean",
        }
        resp = client.post("/api/ab/experiments", json=payload)
        data = resp.json()
        assert data["metric"] == "latency"
        assert data["metric_type"] == "mean"
        assert [v["is_control"] for v in data["variants"]] == [True, False]

    def test_invalid_json_is_a_client_error(self, client: TestClient) -> None:
        resp = client.post(
            "/api/ab/experiments",
            json={"name": "e", "description": "d", "variants_json": "not json"},
        )
        assert resp.status_code == 400

    def test_a_json_object_instead_of_an_array_is_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/ab/experiments",
            json={"name": "e", "description": "d", "variants_json": '{"name": "only"}'},
        )
        assert resp.status_code == 400
        assert "must be an array" in resp.json()["detail"]

    def test_single_variant_is_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/ab/experiments",
            json={"name": "e", "description": "d", "variants_json": '[{"name":"a"}]'},
        )
        assert resp.status_code == 400

    def test_engine_validation_errors_become_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/ab/experiments",
            json={"name": "e", "description": "d", "variants_json": '[{"name":"a"},{"name":"a"}]'},
        )
        assert resp.status_code == 400
        assert "duplicate variant name" in resp.json()["detail"]

    def test_unknown_metric_type_is_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/ab/experiments",
            json={"name": "e", "description": "d", "variants_json": VARIANTS, "metric_type": "median"},
        )
        assert resp.status_code == 400


class TestReading:
    def test_list_shows_variants_and_metric_type(self, client: TestClient) -> None:
        create(client)
        experiments = client.get("/api/ab/experiments").json()["experiments"]
        assert len(experiments) == 1
        assert experiments[0]["metric_type"] == "rate"
        assert [v["name"] for v in experiments[0]["variants"]] == ["Control", "Treatment"]

    def test_get_returns_the_experiment(self, client: TestClient) -> None:
        exp_id = create(client)
        data = client.get(f"/api/ab/experiments/{exp_id}").json()
        assert data["id"] == exp_id
        assert data["status"] == "draft"
        assert data["metric_type"] == "rate"

    def test_get_unknown_is_404(self, client: TestClient) -> None:
        assert client.get("/api/ab/experiments/missing").status_code == 404


class TestStatus:
    @pytest.mark.parametrize("action", ["running", "paused", "completed"])
    def test_transitions(self, client: TestClient, action: str) -> None:
        exp_id = create(client)
        resp = client.post(f"/api/ab/experiments/{exp_id}/status", json={"status": action})
        assert resp.status_code == 200
        assert resp.json()["status"] == action

    def test_invalid_action(self, client: TestClient) -> None:
        exp_id = create(client)
        assert client.post(f"/api/ab/experiments/{exp_id}/status", json={"status": "halt"}).status_code == 400

    def test_unknown_experiment(self, client: TestClient) -> None:
        resp = client.post("/api/ab/experiments/missing/status", json={"status": "running"})
        assert resp.status_code == 404

    def test_delete_removes_the_experiment(self, client: TestClient) -> None:
        exp_id = create(client)
        assert client.delete(f"/api/ab/experiments/{exp_id}").json() == {"ok": True}
        assert client.get(f"/api/ab/experiments/{exp_id}").status_code == 404

    def test_delete_unknown(self, client: TestClient) -> None:
        assert client.delete("/api/ab/experiments/missing").status_code == 404


class TestAssignmentAndRecording:
    def test_assign_returns_a_variant_of_the_running_experiment(self, client: TestClient) -> None:
        exp_id = create(client)
        client.post(f"/api/ab/experiments/{exp_id}/status", json={"status": "running"})
        resp = client.post(f"/api/ab/experiments/{exp_id}/assign", json={"user_id": "u1"})
        assert resp.status_code == 200
        assert resp.json()["variant"] in {"Control", "Treatment"}

    def test_assign_without_a_subject_is_a_client_error(self, client: TestClient) -> None:
        exp_id = create(client)
        client.post(f"/api/ab/experiments/{exp_id}/status", json={"status": "running"})
        resp = client.post(f"/api/ab/experiments/{exp_id}/assign", json={})
        assert resp.status_code == 422
        assert "subject id" in resp.json()["detail"]

    def test_assign_on_a_draft_is_reported_as_not_running(self, client: TestClient) -> None:
        exp_id = create(client)
        resp = client.post(f"/api/ab/experiments/{exp_id}/assign", json={"user_id": "u1"})
        assert resp.status_code == 400

    def test_record_accepts_a_valid_event(self, client: TestClient) -> None:
        exp_id = create(client)
        resp = client.post(
            f"/api/ab/experiments/{exp_id}/record",
            json={"variant": "Control", "metric_name": "conversion", "value": 1.0, "user_id": "u1"},
        )
        assert resp.status_code == 200

    def test_record_on_an_unknown_experiment_is_404(self, client: TestClient) -> None:
        resp = client.post("/api/ab/experiments/missing/record", json={"variant": "Control"})
        assert resp.status_code == 404

    def test_record_of_an_unknown_variant_is_refused_loudly(self, client: TestClient) -> None:
        exp_id = create(client)
        resp = client.post(f"/api/ab/experiments/{exp_id}/record", json={"variant": "Typo"})
        assert resp.status_code == 422
        assert "is not part of experiment" in resp.json()["detail"]

    def test_record_of_an_out_of_range_rate_is_refused(self, client: TestClient) -> None:
        exp_id = create(client)
        resp = client.post(
            f"/api/ab/experiments/{exp_id}/record", json={"variant": "Control", "value": 7.0, "user_id": "u1"}
        )
        assert resp.status_code == 422

    def test_record_of_a_different_metric_is_refused(self, client: TestClient) -> None:
        exp_id = create(client)
        resp = client.post(f"/api/ab/experiments/{exp_id}/record", json={"variant": "Control", "metric_name": "other"})
        assert resp.status_code == 422


class TestResults:
    def test_report_carries_the_method_and_the_unit_counts(self, client: TestClient) -> None:
        exp_id = create(client)
        client.post(f"/api/ab/experiments/{exp_id}/status", json={"status": "running"})
        for i in range(60):
            converted = i % 10 == 0
            client.post(
                f"/api/ab/experiments/{exp_id}/record",
                json={"variant": "Control", "value": 1.0 if converted else 0.0, "user_id": f"c{i}"},
            )
            client.post(
                f"/api/ab/experiments/{exp_id}/record",
                json={"variant": "Treatment", "value": 1.0 if i % 4 == 0 else 0.0, "user_id": f"t{i}"},
            )
        data = client.get(f"/api/ab/experiments/{exp_id}/results").json()
        assert data["method"] == "two_proportion_z_on_units"
        assert data["control"] == "Control"
        assert data["alpha"] == 0.05
        assert data["multiplicity"] == "holm-bonferroni"
        assert data["unit_counts"] == {"Control": 60, "Treatment": 60}
        assert data["total_events"] == 120
        assert data["events_dropped"] == 0
        comparison = data["comparisons"][0]
        assert comparison["variant"] == "Treatment"
        assert -1.0 <= comparison["diff_ci_low"] <= comparison["diff_ci_high"] <= 1.0
        assert comparison["p_adjusted"] >= comparison["p_value"]
        assert data["significant"] is True

    def test_report_of_an_empty_experiment_is_not_significant(self, client: TestClient) -> None:
        exp_id = create(client)
        data = client.get(f"/api/ab/experiments/{exp_id}/results").json()
        assert data["significant"] is False
        assert data["comparisons"][0]["p_value"] == 1.0
        assert data["unit_counts"] == {"Control": 0, "Treatment": 0}

    def test_unknown_experiment_results_404(self, client: TestClient) -> None:
        assert client.get("/api/ab/experiments/missing/results").status_code == 404
