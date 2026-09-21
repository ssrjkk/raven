from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.commands_api import create_commands_router


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_commands_router(data_dir=str(tmp_path)))
    return TestClient(app)


def test_get_theme_default(client: TestClient) -> None:
    resp = client.get("/api/v1/commands/theme")
    assert resp.status_code == 200
    data = resp.json()
    assert "accentColor" in data


def test_save_theme(client: TestClient) -> None:
    resp = client.post("/api/v1/commands/theme", json={"accentColor": "#ff5500"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accentColor"] == "#ff5500"


def test_save_theme_invalid_hex(client: TestClient) -> None:
    resp = client.post("/api/v1/commands/theme", json={"accentColor": "not-hex"})
    assert resp.status_code == 400


def test_save_theme_roundtrip(client: TestClient) -> None:
    client.post("/api/v1/commands/theme", json={"accentColor": "#123456"})
    resp = client.get("/api/v1/commands/theme")
    assert resp.json()["accentColor"] == "#123456"


def test_generate_theme_scheme(client: TestClient) -> None:
    with patch("raven.core.commands_api._llm_palette", return_value=None):
        resp = client.post(
            "/api/v1/commands/theme/generate",
            json={"prompt": "ocean sunset", "use_llm": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "palette" in data
        assert "accent" in data["palette"]
        assert data["name"].startswith("AI")


def test_generate_theme_empty_prompt(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/commands/theme/generate",
        json={"prompt": "   ", "use_llm": False},
    )
    assert resp.status_code == 400


def test_get_contextual_commands(client: TestClient) -> None:
    with patch("raven.core.commands_api._detect_project_state", return_value="empty"):
        resp = client.get("/api/v1/commands/contextual")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1


def test_get_contextual_commands_has_code(client: TestClient) -> None:
    with patch("raven.core.commands_api._detect_project_state", return_value="has_code"):
        resp = client.get("/api/v1/commands/contextual")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
