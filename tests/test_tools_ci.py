# mypy: ignore-errors
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.ci import (
    ci_list_runs,
    ci_list_workflows,
    ci_pipeline_status,
    ci_run_workflow,
    ci_trigger_pipeline,
    register_ci_tools,
)


class TestCITools:
    @pytest.fixture
    def mock_github_token(self) -> None:
        with patch("raven.tools.ci._GITHUB_TOKEN", "fake-token"):
            yield

    @pytest.fixture
    def mock_gitlab_token(self) -> None:
        with patch("raven.tools.ci._GITLAB_TOKEN", "fake-token"):
            yield

    async def test_list_workflows_no_token(self) -> None:
        with patch("raven.tools.ci._GITHUB_TOKEN", ""):
            result = await ci_list_workflows("owner", "repo")
            assert "GITHUB_TOKEN" in result

    async def test_list_workflows_no_owner(self) -> None:
        result = await ci_list_workflows(provider="github")
        assert "owner and repo" in result

    async def test_list_workflows_success(self, mock_github_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"workflows": [{"name": "CI", "state": "active", "id": 123}]})
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
            result = await ci_list_workflows("testowner", "testrepo")
            assert "CI" in result
            assert "active" in result

    async def test_list_workflows_api_error(self, mock_github_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
            result = await ci_list_workflows("owner", "repo")
            assert "404" in result

    async def test_run_workflow_no_token(self) -> None:
        with patch("raven.tools.ci._GITHUB_TOKEN", ""):
            result = await ci_run_workflow("ci.yml", "owner", "repo")
            assert "GITHUB_TOKEN" in result

    async def test_run_workflow_success(self, mock_github_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 204
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
            result = await ci_run_workflow("ci.yml", "owner", "repo")
            assert "triggered" in result.lower()

    async def test_pipeline_status_no_token(self) -> None:
        with patch("raven.tools.ci._GITHUB_TOKEN", ""):
            result = await ci_pipeline_status("123", "owner", "repo")
            assert "GITHUB_TOKEN" in result

    async def test_list_runs_success(self, mock_github_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"workflow_runs": [{"id": 1, "run_number": 1, "name": "CI", "status": "completed", "conclusion": "success", "head_branch": "main"}]})
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
            result = await ci_list_runs("owner", "repo")
            assert "completed" in result

    async def test_gitlab_trigger_pipeline(self, mock_gitlab_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 201
        mock_resp.text = ""
        mock_resp.json = MagicMock(return_value={"id": 42, "status": "pending", "web_url": "https://gitlab.com/pipeline/42"})
        with patch("httpx.AsyncClient") as mock_cls:
            client_mock = AsyncMock()
            client_mock.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__.return_value = client_mock
            result = await ci_trigger_pipeline("my%2Fproject", "main")
            assert "42" in result or "pending" in result

    async def test_gitlab_list_pipelines(self, mock_gitlab_token: None) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=[{"id": 1, "status": "success", "ref": "main"}])
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
            result = await ci_list_workflows("owner", "repo", provider="gitlab")
            assert "success" in result

    async def test_unknown_provider(self) -> None:
        result = await ci_list_workflows(provider="jenkins")
        assert "Unknown provider" in result

    async def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_ci_tools(registry)
        for name in ("ci_list_workflows", "ci_run_workflow", "ci_pipeline_status", "ci_list_runs", "ci_trigger_pipeline", "ci_jenkins_job", "ci_jenkins_status"):
            assert registry.get(name) is not None
