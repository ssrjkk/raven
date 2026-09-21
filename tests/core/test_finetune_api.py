from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.finetune_api as ft_mod
from raven.core.finetune_api import create_finetune_router


@pytest.fixture()
def mock_builder() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_pipeline() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_builder: MagicMock, mock_pipeline: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    orig_builder = ft_mod._builder
    orig_pipeline = ft_mod._pipeline
    ft_mod._builder = mock_builder
    ft_mod._pipeline = mock_pipeline
    try:
        app.include_router(create_finetune_router())
        yield TestClient(app)
    finally:
        ft_mod._builder = orig_builder
        ft_mod._pipeline = orig_pipeline


def test_dataset_stats(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = {"conversations": 5, "code_samples": 10}
    resp = client.get("/api/finetune/dataset/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversations"] == 5


def test_add_conversation(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = {"conversations": 1, "code_samples": 0}
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={"system_prompt": "You are helpful", "messages_json": '[{"role":"user","content":"hi"}]'},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_add_conversation_invalid_json(client: TestClient) -> None:
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={"system_prompt": "", "messages_json": "not json"},
    )
    assert resp.status_code == 400


def test_add_code(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = {"conversations": 0, "code_samples": 1}
    resp = client.post(
        "/api/finetune/dataset/code",
        json={"code": "def hello(): pass", "language": "python", "description": "test"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_model_info(client: TestClient, mock_pipeline: MagicMock) -> None:
    mock_pipeline.get_model_info.return_value = {"model_type": "llama", "loaded": False}
    resp = client.get("/api/finetune/model/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_type"] == "llama"


def test_list_checkpoints(client: TestClient, mock_pipeline: MagicMock) -> None:
    cp = MagicMock()
    cp.step = 100
    cp.epoch = 1
    cp.path = "/path/to/cp"
    mock_pipeline.list_checkpoints.return_value = [cp]

    resp = client.get("/api/finetune/checkpoints")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["checkpoints"]) == 1
    assert data["checkpoints"][0]["step"] == 100


def test_list_checkpoints_empty(client: TestClient, mock_pipeline: MagicMock) -> None:
    mock_pipeline.list_checkpoints.return_value = []
    resp = client.get("/api/finetune/checkpoints")
    assert resp.status_code == 200
    assert resp.json()["checkpoints"] == []
