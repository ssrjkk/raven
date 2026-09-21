from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from raven.core.git_api import create_git_router


@pytest.fixture()
def client():
    router = create_git_router()
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def mock_git(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("raven.core.git_api.GitIntegration", lambda: mock)
    return mock


class TestGitStatus:
    def test_status(self, client, mock_git):
        mock_git.status.return_value = {"branch": "main", "clean": True}
        resp = client.get("/api/git/status")
        assert resp.status_code == 200
        assert resp.json()["branch"] == "main"

    def test_branch(self, client, mock_git):
        mock_git.get_branch.return_value = "main"
        mock_git.is_branch.return_value = True
        mock_git.is_repo.return_value = True
        resp = client.get("/api/git/branch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["branch"] == "main"
        assert data["is_branch"] is True
        assert data["is_repo"] is True

    def test_branches(self, client, mock_git):
        mock_git._run.return_value = ("* main\n  dev\n  remotes/origin/main", "")
        mock_git.get_branch.return_value = "main"
        resp = client.get("/api/git/branches")
        assert resp.status_code == 200
        data = resp.json()
        assert "main" in data["branches"]
        assert data["current"] == "main"

    def test_log(self, client, mock_git):
        mock_git.get_log.return_value = [{"hash": "abc", "msg": "init"}]
        resp = client.get("/api/git/log")
        assert resp.status_code == 200
        assert resp.json()[0]["hash"] == "abc"


class TestGitDiff:
    def test_diff(self, client, mock_git):
        mock_git.get_diff.return_value = "diff --git a/f b/f"
        resp = client.get("/api/git/diff")
        assert resp.status_code == 200
        assert "diff" in resp.json()

    def test_diff_commit(self, client, mock_git):
        mock_git._run.return_value = (
            "diff --git a/f b/f\n@@ -1,1 +1,2 @@\n-old\n+new\n+added",
            "",
        )
        resp = client.get("/api/git/diff/commit/abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert "diff" in data
        assert "files" in data


class TestGitCommit:
    def test_commit(self, client, mock_git):
        result = MagicMock()
        result.success = True
        result.message = "ok"
        result.commit_hash = "abc123"
        result.error = ""
        mock_git.commit.return_value = result
        resp = client.post("/api/git/commit?message=test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_push(self, client, mock_git):
        mock_git._run.return_value = ("", "Everything up-to-date")
        resp = client.post("/api/git/push")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_pull(self, client, mock_git):
        mock_git._run.return_value = ("Already up to date.", "")
        resp = client.post("/api/git/pull")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_checkout(self, client, mock_git):
        mock_git._run.return_value = ("Switched to branch 'dev'", "")
        resp = client.post("/api/git/checkout?branch=dev")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["branch"] == "dev"
