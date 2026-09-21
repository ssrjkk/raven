from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.cicd_api import create_cicd_router


class TestCicdApi:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(create_cicd_router())
        return TestClient(app)

    def test_workflows_endpoint(self, client):
        with patch("raven.core.cicd_api.ci_list_workflows", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = "Workflows list"
            response = client.get("/api/cicd/workflows?owner=test&repo=repo&provider=github")
            assert response.status_code == 200
            assert response.json() == {"text": "Workflows list"}
            mock_list.assert_called_once_with(owner="test", repo="repo", provider="github")

    def test_workflows_with_defaults(self, client):
        with patch("raven.core.cicd_api.ci_list_workflows", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = "List"
            response = client.get("/api/cicd/workflows")
            assert response.status_code == 200
            mock_list.assert_called_once_with(owner="", repo="", provider="github")

    def test_run_endpoint(self, client):
        with patch("raven.core.cicd_api.ci_run_workflow", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Workflow started"
            response = client.post(
                "/api/cicd/run",
                json={
                    "workflow_id": "wf1",
                    "owner": "test",
                    "repo": "repo",
                    "ref": "main",
                    "inputs": "key=value",
                    "provider": "github",
                },
            )
            assert response.status_code == 200
            assert response.json() == {"text": "Workflow started"}
            mock_run.assert_called_once()

    def test_run_with_defaults(self, client):
        with patch("raven.core.cicd_api.ci_run_workflow", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Started"
            response = client.post("/api/cicd/run", json={})
            assert response.status_code == 200
            mock_run.assert_called_once_with(
                workflow_id="", owner="", repo="", ref="main", inputs="", provider="github"
            )

    def test_status_endpoint(self, client):
        with patch("raven.core.cicd_api.ci_pipeline_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = "Pipeline status"
            response = client.get("/api/cicd/status?pipeline_id=p1&owner=test&repo=repo")
            assert response.status_code == 200
            assert response.json() == {"text": "Pipeline status"}
            mock_status.assert_called_once()

    def test_runs_endpoint(self, client):
        with patch("raven.core.cicd_api.ci_list_runs", new_callable=AsyncMock) as mock_runs:
            mock_runs.return_value = "Runs list"
            response = client.get("/api/cicd/runs?owner=test&repo=repo&branch=main&status=success")
            assert response.status_code == 200
            assert response.json() == {"text": "Runs list"}
            mock_runs.assert_called_once()

    def test_runs_with_defaults(self, client):
        with patch("raven.core.cicd_api.ci_list_runs", new_callable=AsyncMock) as mock_runs:
            mock_runs.return_value = "List"
            response = client.get("/api/cicd/runs")
            assert response.status_code == 200
            mock_runs.assert_called_once_with(owner="", repo="", branch="", status="", provider="github")
