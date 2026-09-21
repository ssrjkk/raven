from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.scaffold_api import (
    TEMPLATES,
    _build_tree,
    _gen_fastapi_react,
    _gen_python_cli,
    _gen_rust_cli,
    _gen_ts_react,
    create_scaffold_router,
)


@pytest.fixture()
def client(tmp_path: pytest.TempPathFactory) -> TestClient:
    app = FastAPI()
    app.include_router(create_scaffold_router(workspace=str(tmp_path)))
    return TestClient(app)


def test_list_plans(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(TEMPLATES)
    ids = [p["id"] for p in data]
    assert "fastapi-react" in ids
    assert "python-cli" in ids


def test_get_plan(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans/fastapi-react")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "fastapi-react"
    assert "questions" in data


def test_get_plan_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans/nonexistent")
    assert resp.status_code == 404


def test_generate_fastapi_react(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "fastapi-react", "answers": {"project_name": "test-app", "use_auth": True, "use_db": "sqlite", "use_docker": False}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "tree" in data
    assert len(data["files"]) > 0


def test_generate_python_cli(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "python-cli", "answers": {"project_name": "my-cli", "use_rich": True}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_ts_react(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "ts-react", "answers": {"project_name": "my-app", "use_router": True, "use_state": "zustand"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_rust_cli(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "rust-cli", "answers": {"project_name": "my-tool", "use_serde": True, "use_http": False}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "nonexistent", "answers": {}},
    )
    assert resp.status_code == 404


def test_gen_fastapi_react_function(tmp_path: pytest.TempPathFactory) -> None:
    target = tmp_path / "test"  # type: ignore[operator]
    target.mkdir()
    files = _gen_fastapi_react(target, {"project_name": "test", "use_auth": False, "use_db": "sqlite", "use_docker": False})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "backend/requirements.txt" in paths
    assert "backend/app/main.py" in paths


def test_gen_python_cli_function(tmp_path: pytest.TempPathFactory) -> None:
    target = tmp_path / "test"  # type: ignore[operator]
    target.mkdir()
    files = _gen_python_cli(target, {"project_name": "my-cli", "use_rich": False})
    assert len(files) >= 3
    paths = [f["path"] for f in files]
    assert "pyproject.toml" in paths


def test_gen_ts_react_function(tmp_path: pytest.TempPathFactory) -> None:
    target = tmp_path / "test"  # type: ignore[operator]
    target.mkdir()
    files = _gen_ts_react(target, {"project_name": "app", "use_router": False, "use_state": "none"})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "package.json" in paths


def test_gen_rust_cli_function(tmp_path: pytest.TempPathFactory) -> None:
    target = tmp_path / "test"  # type: ignore[operator]
    target.mkdir()
    files = _gen_rust_cli(target, {"project_name": "tool", "use_serde": False, "use_http": False})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "Cargo.toml" in paths


def test_build_tree(tmp_path: pytest.TempPathFactory) -> None:
    root = tmp_path / "project"  # type: ignore[operator]
    root.mkdir()
    (root / "file1.txt").write_text("a")
    sub = root / "subdir"
    sub.mkdir()
    (sub / "file2.txt").write_text("b")
    tree = _build_tree(root)
    assert "project" in tree
    assert "file1.txt" in tree
    assert "subdir" in tree
    assert "file2.txt" in tree
