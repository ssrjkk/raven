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


def _consent_stats(conversations: int, code: int = 0) -> dict[str, object]:
    return {
        "conversations": conversations,
        "code_samples": code,
        "consented": {"conversations": conversations, "code_samples": code},
        "excluded_without_consent": 0,
        "policy": {"require_consent": True, "redact_pii": True},
        "config": {"max_length": 2048, "test_split": 0.1},
    }


def test_add_conversation(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = _consent_stats(1)
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={
            "system_prompt": "You are helpful",
            "messages_json": '[{"role":"user","content":"hi"}]',
            "consented": True,
            "source": "operator-demo",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["consented"] == 1
    assert mock_builder.add_conversation.call_args.args[0].consented is True


def test_add_conversation_without_consent_is_refused(client: TestClient, mock_builder: MagicMock) -> None:
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={"messages_json": '[{"role":"user","content":"hi"}]'},
    )
    assert resp.status_code == 400
    assert "consented=true" in resp.json()["detail"]
    mock_builder.add_conversation.assert_not_called()


def test_add_conversation_empty_messages(client: TestClient) -> None:
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={"messages_json": "[]", "consented": True},
    )
    assert resp.status_code == 400


def test_add_conversation_invalid_json(client: TestClient) -> None:
    resp = client.post(
        "/api/finetune/dataset/conversation",
        json={"system_prompt": "", "messages_json": "not json", "consented": True},
    )
    assert resp.status_code == 400


def test_add_code(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = _consent_stats(0, 1)
    resp = client.post(
        "/api/finetune/dataset/code",
        json={"code": "def hello(): pass", "language": "python", "description": "test", "consented": True},
    )
    assert resp.status_code == 200
    assert resp.json()["consented"] == 1


def test_add_code_without_consent_is_refused(client: TestClient, mock_builder: MagicMock) -> None:
    resp = client.post("/api/finetune/dataset/code", json={"code": "print(1)"})
    assert resp.status_code == 400
    mock_builder.add_code.assert_not_called()


def test_dataset_clear_reports_what_it_removed(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.stats.return_value = _consent_stats(3, 2)
    resp = client.post("/api/finetune/dataset/clear")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 5
    mock_builder.clear.assert_called_once()


def test_dataset_card_is_served(client: TestClient, mock_builder: MagicMock) -> None:
    mock_builder.dataset_card.return_value = {"rows": {"conversations": 1}, "corpus_sha256": "ab" * 32}
    resp = client.get("/api/finetune/dataset/card")
    assert resp.status_code == 200
    assert resp.json()["corpus_sha256"].startswith("ab")


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
