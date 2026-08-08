from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.scaffold_api as sa


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, Path]:
    ws = tmp_path / "ws"
    ws.mkdir()
    app = FastAPI()
    app.include_router(sa.create_scaffold_router(str(ws)))
    return TestClient(app), ws


def test_list_plans(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.get("/api/v1/scaffold/plans")
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) == 4
    ids = {p["id"] for p in plans}
    assert ids == {"fastapi-react", "python-cli", "ts-react", "rust-cli"}


def test_get_plan_ok(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.get("/api/v1/scaffold/plans/fastapi-react")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "fastapi-react"
    assert body["questions"][0]["key"] == "project_name"


def test_get_plan_not_found(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.get("/api/v1/scaffold/plans/nope")
    assert resp.status_code == 404


def test_generate_fastapi_react_full(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "fastapi-react",
            "answers": {"project_name": "webapp", "use_auth": True, "use_db": "postgres", "use_docker": True},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    paths = {f["path"] for f in body["files"]}
    assert "backend/app/main.py" in paths
    assert "backend/app/auth.py" in paths
    assert "Dockerfile" in paths
    assert "docker-compose.yml" in paths
    assert (ws / "webapp" / "backend" / "app").is_dir()
    assert (ws / "webapp" / "frontend" / "src" / "components").is_dir()
    assert "webapp" in body["tree"]


def test_generate_fastapi_react_minimal(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "fastapi-react",
            "answers": {"project_name": "mini", "use_auth": False, "use_db": "sqlite", "use_docker": False},
        },
    )
    assert resp.status_code == 200
    paths = {f["path"] for f in resp.json()["files"]}
    assert "backend/app/auth.py" not in paths
    assert "Dockerfile" not in paths
    assert (ws / "mini" / "backend").is_dir()


def test_generate_python_cli(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "python-cli", "answers": {"project_name": "my-cli", "use_rich": True}},
    )
    assert resp.status_code == 200
    files = {f["path"]: f["content"] for f in resp.json()["files"]}
    assert "src/my_cli/cli.py" in files
    assert "from rich.console import Console" in files["src/my_cli/cli.py"]
    assert "tests/test_cli.py" in files
    assert "rich>=13.0" in files["pyproject.toml"]
    assert (ws / "my-cli" / "src").is_dir()


def test_generate_python_cli_no_rich(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "python-cli", "answers": {"project_name": "plain", "use_rich": False}},
    )
    assert resp.status_code == 200
    files = {f["path"]: f["content"] for f in resp.json()["files"]}
    assert "click.echo(msg)" in files["src/plain/cli.py"]
    assert "rich>=13.0" not in files["pyproject.toml"]


def test_generate_ts_react_full(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "ts-react",
            "answers": {"project_name": "sapp", "use_router": True, "use_state": "zustand"},
        },
    )
    assert resp.status_code == 200
    files = {f["path"]: f["content"] for f in resp.json()["files"]}
    assert "src/App.tsx" in files
    assert "src/pages/Home.tsx" in files
    assert "src/pages/About.tsx" in files
    assert "react-router-dom" in files["package.json"]
    assert "zustand" in files["package.json"]
    assert (ws / "sapp" / "src").is_dir()


def test_generate_ts_react_minimal(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "ts-react", "answers": {"project_name": "mini", "use_router": False, "use_state": "none"}},
    )
    assert resp.status_code == 200
    files = {f["path"]: f["content"] for f in resp.json()["files"]}
    assert "src/pages/Home.tsx" not in files
    assert "react-router-dom" not in files["package.json"]
    assert "zustand" not in files["package.json"]


def test_generate_rust_cli_full(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "rust-cli", "answers": {"project_name": "tool", "use_serde": True, "use_http": True}},
    )
    assert resp.status_code == 200
    files = {f["path"]: f["content"] for f in resp.json()["files"]}
    assert "src/main.rs" in files
    assert "Cargo.toml" in files
    assert "reqwest" in files["Cargo.toml"]
    assert "serde = { features" in files["Cargo.toml"]
    assert (ws / "tool" / "src").is_dir()


def test_generate_rust_cli_minimal(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "rust-cli", "answers": {"project_name": "bare", "use_serde": False, "use_http": False}},
    )
    assert resp.status_code == 200
    cargo = {f["path"]: f["content"] for f in resp.json()["files"]}["Cargo.toml"]
    assert "serde" not in cargo
    assert "reqwest" not in cargo


def test_generate_unknown_template(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "nope", "answers": {}},
    )
    assert resp.status_code == 404


def test_generate_access_denied(client: tuple[TestClient, Path]) -> None:
    c, _ = client
    resp = c.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "python-cli", "answers": {"project_name": "evil"}, "output_dir": "../../.."},
    )
    assert resp.status_code == 403


def test_generate_default_project_name(client: tuple[TestClient, Path]) -> None:
    c, ws = client
    resp = c.post("/api/v1/scaffold/generate", json={"template_id": "python-cli", "answers": {}})
    assert resp.status_code == 200
    assert (ws / "my-app").is_dir()
