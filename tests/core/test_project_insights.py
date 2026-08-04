from __future__ import annotations

from pathlib import Path

import pytest


def _sample_commits():
    return [
        {"hash": "a1", "message": "feat: add login", "author": "u", "date": "2026-07-01", "date_iso": "2026-07-01T10:00:00+00:00", "files": []},
        {"hash": "a2", "message": "fix: typo", "author": "u", "date": "2026-07-01", "date_iso": "2026-07-01T12:00:00+00:00", "files": []},
        {"hash": "a3", "message": "docs: readme", "author": "u", "date": "2026-07-02", "date_iso": "2026-07-02T09:00:00+00:00", "files": []},
    ]


class TestComputeProjectInsights:
    def test_empty_workspace_returns_zeroed_insight(self, tmp_path):
        from raven.core.project_insights_api import compute_project_insights

        result = compute_project_insights("demo", tmp_path, [], 30)
        assert result["project_id"] == "demo"
        assert result["commits"] == 0
        assert result["files"] == 0
        assert result["code_lines"] == 0
        assert result["active_days"] == 0
        assert len(result["trend"]) == 30

    def test_commits_populate_metrics(self, tmp_path):
        from raven.core.project_insights_api import compute_project_insights

        (tmp_path / "main.py").write_text("print('hi')\nprint('there')\n", encoding="utf-8")
        result = compute_project_insights("demo", tmp_path, _sample_commits(), 30)
        assert result["commits"] == 3
        assert result["active_days"] == 2
        assert result["files"] == 1
        assert result["code_lines"] == 2
        assert result["time_saved_minutes"] > 0
        assert 0 <= result["ai_contribution_percent"] <= 100
        assert result["token_cost_estimate"] >= 0

    def test_success_rate_penalized_by_reverts(self, tmp_path):
        from raven.core.project_insights_api import compute_project_insights

        commits = _sample_commits()
        commits.append({"hash": "a4", "message": "Revert \"feat: add login\"", "author": "u", "date": "2026-07-03", "date_iso": "2026-07-03T10:00:00+00:00", "files": []})
        result = compute_project_insights("demo", tmp_path, commits, 30)
        assert result["commits"] == 4
        assert result["success_rate"] == pytest.approx(75.0)

    def test_no_reverts_success_rate_100(self, tmp_path):
        from raven.core.project_insights_api import compute_project_insights

        result = compute_project_insights("demo", tmp_path, _sample_commits(), 30)
        assert result["success_rate"] == 100.0

    def test_trend_length_matches_days(self, tmp_path):
        from raven.core.project_insights_api import compute_project_insights

        result = compute_project_insights("demo", tmp_path, [], 7)
        assert len(result["trend"]) == 7
        assert all(isinstance(p["date"], str) and isinstance(p["commits"], int) for p in result["trend"])


class TestProjectInsightsRouter:
    def test_router_registers_endpoint(self):
        from fastapi.routing import APIRoute

        from raven.core.project_insights_api import create_project_insights_router

        router = create_project_insights_router(workspace=".")
        paths = {r.path for r in router.routes if isinstance(r, APIRoute)}
        assert "/api/v1/projects/{project_id}/insights" in paths

    def test_endpoint_returns_insight(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.project_insights_api import create_project_insights_router

        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        app = FastAPI()
        app.include_router(create_project_insights_router(workspace=str(tmp_path)))
        client = TestClient(app)

        response = client.get("/api/v1/projects/demo/insights")
        assert response.status_code == 200
        body = response.json()
        assert body["project_id"] == "demo"
        assert body["commits"] == 0
        assert len(body["trend"]) == 30

    def test_endpoint_respects_days_limit(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.project_insights_api import create_project_insights_router

        app = FastAPI()
        app.include_router(create_project_insights_router(workspace=str(tmp_path)))
        client = TestClient(app)

        response = client.get("/api/v1/projects/demo/insights?days=7")
        assert response.status_code == 200
        assert len(response.json()["trend"]) == 7
