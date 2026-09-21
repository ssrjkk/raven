from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.plugin_api as plugin_mod
from raven.core.plugin_api import create_plugin_router


@pytest.fixture()
def mock_catalog() -> MagicMock:
    cat = MagicMock()
    cat.sync = AsyncMock()
    return cat


@pytest.fixture()
def mock_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_catalog: MagicMock, mock_manager: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    orig_cat = plugin_mod._catalog
    orig_mgr = plugin_mod._manager
    plugin_mod._catalog = mock_catalog
    plugin_mod._manager = mock_manager
    try:
        app.include_router(create_plugin_router())
        yield TestClient(app)
    finally:
        plugin_mod._catalog = orig_cat
        plugin_mod._manager = orig_mgr


def test_list_plugins(client: TestClient, mock_manager: MagicMock) -> None:
    p = MagicMock()
    p.metadata.id = "p1"
    p.metadata.name = "Test Plugin"
    p.metadata.version = "1.0.0"
    p.metadata.description = "A test plugin"
    p.metadata.author = "author"
    p.metadata.category = MagicMock()
    p.metadata.category.value = "tools"
    p.status = MagicMock()
    p.status.value = "active"
    p.install_path = "/path/to/plugin"
    p.installed_at = "2026-01-01"
    mock_manager.list_installed.return_value = [p]

    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Plugin"


def test_catalog(client: TestClient, mock_catalog: MagicMock) -> None:
    p = MagicMock()
    p.id = "p1"
    p.name = "Test"
    p.version = "1.0"
    p.description = "desc"
    p.author = "author"
    p.tags = ["test"]
    p.category = MagicMock()
    p.category.value = "tools"
    p.icon = "icon.png"
    mock_catalog._plugins = {"p1": p}

    resp = client.get("/api/plugins/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


def test_catalog_with_category(client: TestClient, mock_catalog: MagicMock) -> None:
    p1 = MagicMock()
    p1.id = "p1"
    p1.name = "Test"
    p1.version = "1.0"
    p1.description = "desc"
    p1.author = "author"
    p1.tags = []
    p1.category = MagicMock()
    p1.category.value = "tools"
    p1.icon = ""

    p2 = MagicMock()
    p2.id = "p2"
    p2.name = "Other"
    p2.version = "1.0"
    p2.description = "desc"
    p2.author = "author"
    p2.tags = []
    p2.category = MagicMock()
    p2.category.value = "other"
    p2.icon = ""

    mock_catalog._plugins = {"p1": p1, "p2": p2}

    resp = client.get("/api/plugins/catalog", params={"category": "tools"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_search(client: TestClient, mock_catalog: MagicMock) -> None:
    p = MagicMock()
    p.id = "p1"
    p.name = "Test"
    p.version = "1.0"
    p.description = "desc"
    p.author = "author"
    p.tags = []
    p.category = MagicMock()
    p.category.value = "tools"
    mock_catalog.search.return_value = [p]

    resp = client.get("/api/plugins/search", params={"q": "test"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_search_empty(client: TestClient) -> None:
    resp = client.get("/api/plugins/search", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


def test_install(client: TestClient, mock_manager: MagicMock) -> None:
    result = MagicMock()
    result.metadata.name = "test-plugin"
    result.metadata.version = "1.0.0"
    result.status = MagicMock()
    result.status.value = "active"
    mock_manager.install_plugin = AsyncMock(return_value=result)

    resp = client.post("/api/plugins/install", json={"url": "https://example.com/plugin"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_install_missing_url(client: TestClient) -> None:
    resp = client.post("/api/plugins/install", json={})
    assert resp.status_code == 400


def test_uninstall(client: TestClient, mock_manager: MagicMock) -> None:
    mock_manager.uninstall_plugin.return_value = True
    resp = client.post("/api/plugins/uninstall/test-plugin")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_update(client: TestClient, mock_manager: MagicMock) -> None:
    result = MagicMock()
    result.metadata.name = "test-plugin"
    result.metadata.version = "2.0.0"
    result.status = MagicMock()
    result.status.value = "active"
    mock_manager.update_plugin = AsyncMock(return_value=result)

    resp = client.post("/api/plugins/update/test-plugin")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_top(client: TestClient, mock_catalog: MagicMock) -> None:
    p = MagicMock()
    p.id = "p1"
    p.name = "Top Plugin"
    p.version = "1.0"
    p.description = "desc"
    p.author = "author"
    p.category = MagicMock()
    p.category.value = "tools"
    mock_catalog.get_top_rated.return_value = [(p, 4.5)]

    resp = client.get("/api/plugins/top")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rating"] == 4.5
