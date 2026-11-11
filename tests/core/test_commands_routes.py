from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.commands_api import create_commands_router

ROOT = Path(__file__).resolve().parents[2]


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


def spa_routes() -> set[str]:
    """The paths the console router answers, read out of the SPA source."""
    source = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    paths = set(re.findall(r'<Route[^>]*?\bpath="([^"]*)"', source, re.DOTALL))
    return {path.lstrip("/") for path in paths if path not in ("*", "login", "/login")}


def test_every_contextual_command_leads_somewhere(client: TestClient) -> None:
    """The palette navigates to `route`, and it drops a command that has none - so a command
    served without a route, or with one the console does not have, is an entry that either never
    appears or opens nothing. Both used to be true: the payload carried an `action_endpoint`
    pointing at /api/v1/ai/* routes that no router serves, and the client ignored it."""
    for state in ("empty", "has_code"):
        with patch("raven.core.commands_api._detect_project_state", return_value=state):
            data = client.get("/api/v1/commands/contextual").json()
        assert data, state
        routes = spa_routes()
        for command in data:
            route = command.get("route")
            assert isinstance(route, str) and route, command
            assert route.lstrip("/") in routes, (command["id"], route, sorted(routes)[:4])
            assert "action_endpoint" not in command, command
