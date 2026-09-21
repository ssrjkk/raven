from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.workflow_api as wf_mod
from raven.core.workflow_api import create_workflow_router


@pytest.fixture()
def mock_store() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_store: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    original = wf_mod._store
    wf_mod._store = mock_store
    try:
        app.include_router(create_workflow_router())
        yield TestClient(app)
    finally:
        wf_mod._store = original


def test_list_templates(client: TestClient, mock_store: MagicMock) -> None:
    t = MagicMock()
    t.id = "t1"
    t.name = "Test"
    t.description = "desc"
    t.category = MagicMock()
    t.category.value = "dev"
    t.trigger = MagicMock()
    t.trigger.value = "manual"
    t.icon = "code"
    t.config_schema = {}
    t.steps_goal = None
    t.predefined_steps = None
    mock_store.list_templates.return_value = [t]

    resp = client.get("/api/workflows/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["templates"][0]["id"] == "t1"


def test_list_templates_with_category(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.list_templates.return_value = []
    resp = client.get("/api/workflows/templates", params={"category": "dev"})
    assert resp.status_code == 200
    mock_store.list_templates.assert_called_with(category="dev")


def test_list_categories(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.list_categories.return_value = ["dev", "ops", "data"]
    resp = client.get("/api/workflows/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["categories"] == ["dev", "ops", "data"]


def test_get_template(client: TestClient, mock_store: MagicMock) -> None:
    t = MagicMock()
    t.id = "t1"
    t.name = "Test"
    t.description = "desc"
    t.category = MagicMock()
    t.category.value = "dev"
    t.trigger = MagicMock()
    t.trigger.value = "manual"
    t.icon = "code"
    t.config_schema = {}
    t.default_schedule = "0 * * * *"
    t.default_interval = 3600
    t.steps_goal = 5
    t.predefined_steps = []
    mock_store.get.return_value = t

    resp = client.get("/api/workflows/templates/t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "t1"
    assert data["steps_goal"] == 5


def test_get_template_not_found(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.get.return_value = None
    resp = client.get("/api/workflows/templates/nonexistent")
    assert resp.status_code == 404


def test_instantiate_not_found(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.get.return_value = None
    resp = client.post("/api/workflows/templates/nonexistent/instantiate", json={})
    assert resp.status_code == 404


def test_schedule_not_found(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.get.return_value = None
    resp = client.post("/api/workflows/templates/nonexistent/schedule", json={})
    assert resp.status_code == 404
