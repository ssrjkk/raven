from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from raven.core.web_search_api import create_web_search_router


@pytest.fixture()
def client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_web_search_router())
    return TestClient(app)


def test_search(client: TestClient) -> None:
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"title": "Test", "url": "https://example.com", "snippet": "snippet"}
    with patch("raven.core.web_search_api._get_tool", new_callable=AsyncMock) as mock_get:
        tool = AsyncMock()
        tool.search = AsyncMock(return_value=[mock_result])
        mock_get.return_value = tool
        resp = client.post("/api/web-search/search", json={"query": "test", "provider": "duckduckgo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["provider"] == "duckduckgo"


def test_search_invalid_provider(client: TestClient) -> None:
    with patch("raven.core.web_search_api._get_tool", new_callable=AsyncMock) as mock_get:
        tool = AsyncMock()
        mock_get.return_value = tool
        resp = client.post("/api/web-search/search", json={"query": "test", "provider": "invalid_provider"})
        assert resp.status_code == 400


def test_search_error(client: TestClient) -> None:
    with patch("raven.core.web_search_api._get_tool", new_callable=AsyncMock) as mock_get:
        tool = AsyncMock()
        tool.search = AsyncMock(side_effect=RuntimeError("search failed"))
        mock_get.return_value = tool
        resp = client.post("/api/web-search/search", json={"query": "test"})
        assert resp.status_code == 500


def test_failover(client: TestClient) -> None:
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"title": "T", "url": "https://x.com", "snippet": "s"}
    with patch("raven.core.web_search_api._get_tool", new_callable=AsyncMock) as mock_get:
        tool = AsyncMock()
        tool.search_with_failover = AsyncMock(return_value=[mock_result])
        mock_get.return_value = tool
        resp = client.post(
            "/api/web-search/failover",
            json={"query": "test", "providers": ["duckduckgo", "bing"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1


def test_failover_no_providers(client: TestClient) -> None:
    with patch("raven.core.web_search_api._get_tool", new_callable=AsyncMock) as mock_get:
        tool = AsyncMock()
        tool.search_with_failover = AsyncMock(return_value=[])
        mock_get.return_value = tool
        resp = client.post("/api/web-search/failover", json={"query": "test"})
        assert resp.status_code == 200


def test_providers(client: TestClient) -> None:
    resp = client.get("/api/web-search/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert len(data["providers"]) > 0
    names = [p["name"] for p in data["providers"]]
    assert "duckduckgo" in names
