from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.github_api as gh


class FakeSecret:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class FakeSecrets:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str, default: str = "") -> str:
        return self.store.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.store[key] = value


class FakeResp:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.is_success:
            req = httpx.Request("GET", "https://api.github.com/")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(f"Error {self.status_code}", request=req, response=resp)


class FakeClient:
    def __init__(self) -> None:
        self.responses: list[FakeResp] = []
        self.calls: list[tuple[str, str, Any]] = []

    def add(self, resp: FakeResp) -> None:
        self.responses.append(resp)

    def _next(self) -> FakeResp:
        if not self.responses:
            raise AssertionError("no response configured")
        return self.responses.pop(0)

    async def get(self, url: str, params: dict[str, Any] | None = None) -> FakeResp:
        self.calls.append(("get", url, params))
        return self._next()

    async def post(self, url: str, json: Any = None) -> FakeResp:
        self.calls.append(("post", url, json))
        return self._next()

    async def put(self, url: str, json: Any = None) -> FakeResp:
        self.calls.append(("put", url, json))
        return self._next()

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeProc:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[TestClient, FakeClient, FakeSecrets]:
    fake = FakeClient()
    secrets = FakeSecrets()
    monkeypatch.setattr(gh, "_client", lambda: fake)
    monkeypatch.setattr(
        gh, "settings", SimpleNamespace(github_token=FakeSecret("ghp_test"), resolved_workspace=str(tmp_path))
    )
    monkeypatch.setattr(gh, "secrets", secrets)
    app = FastAPI()
    app.include_router(gh.create_github_router())
    client = TestClient(app, raise_server_exceptions=False)
    return client, fake, secrets


def _no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(gh, "_client", lambda: FakeClient())
    monkeypatch.setattr(
        gh, "settings", SimpleNamespace(github_token=FakeSecret(""), resolved_workspace=str(tmp_path))
    )
    monkeypatch.setattr(gh, "secrets", FakeSecrets())
    app = FastAPI()
    app.include_router(gh.create_github_router())
    return TestClient(app, raise_server_exceptions=False)


def test_github_user_requires_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/user")
    assert resp.status_code == 401


def test_github_user_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"login": "ssrjkk"}))
    resp = client.get("/api/github/user")
    assert resp.status_code == 200
    assert resp.json() == {"login": "ssrjkk"}


def test_github_user_error(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(500, None, "boom"))
    resp = client.get("/api/github/user")
    assert resp.status_code == 500


def test_list_repos_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"name": "raven"}]))
    resp = client.get("/api/github/repos", params={"page": 2, "per_page": 5, "sort": "pushed"})
    assert resp.status_code == 200
    assert resp.json() == [{"name": "raven"}]
    url, params = fake.calls[0][1], fake.calls[0][2]
    assert url == "https://api.github.com/user/repos"
    assert params == {"page": 2, "per_page": 5, "sort": "pushed", "type": "owner"}


def test_list_repos_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/repos")
    assert resp.status_code == 401


def test_get_repo(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"full_name": "o/r"}))
    resp = client.get("/api/github/repos/o/r")
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "o/r"
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/"


def test_get_repo_not_found(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(404, {"message": "nope"}))
    resp = client.get("/api/github/repos/o/r")
    assert resp.status_code == 404


def test_get_repo_rate_limited(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(403, {"message": "rate"}))
    resp = client.get("/api/github/repos/o/r")
    assert resp.status_code == 403


def test_get_repo_server_error(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(500, None, "oops"))
    resp = client.get("/api/github/repos/o/r")
    assert resp.status_code == 500


def test_list_branches(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"name": "main"}]))
    resp = client.get("/api/github/repos/o/r/branches")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/branches"


def test_get_contents_with_ref(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"name": "f.py"}))
    resp = client.get("/api/github/repos/o/r/contents/src", params={"ref": "dev"})
    assert resp.status_code == 200
    assert fake.calls[0][2] == {"ref": "dev"}


def test_get_contents_no_ref(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"name": "f.py"}))
    resp = client.get("/api/github/repos/o/r/contents/")
    assert resp.status_code == 200
    assert fake.calls[0][2] == {}


def test_list_pulls(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"number": 1}]))
    resp = client.get("/api/github/repos/o/r/pulls", params={"state": "closed"})
    assert resp.status_code == 200
    assert fake.calls[0][2]["state"] == "closed"


def test_get_pull(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"number": 7}))
    resp = client.get("/api/github/repos/o/r/pulls/7")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/pulls/7"


def test_get_pull_files(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"filename": "a.py"}]))
    resp = client.get("/api/github/repos/o/r/pulls/7/files")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/pulls/7/files"


def test_list_issues(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"number": 3}]))
    resp = client.get("/api/github/repos/o/r/issues")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/issues"


def test_create_pr(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(201, {"number": 42}))
    resp = client.post(
        "/api/github/repos/o/r/pulls",
        json={"owner": "o", "repo": "r", "title": "T", "body": "B", "head": "feat", "base": "main"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"number": 42}
    payload = fake.calls[0][2]
    assert payload == {"title": "T", "body": "B", "head": "feat", "base": "main"}
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/pulls"


def test_create_pr_error(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(422, None, "invalid"))
    resp = client.post(
        "/api/github/repos/o/r/pulls",
        json={"owner": "o", "repo": "r", "title": "T"},
    )
    assert resp.status_code == 422
    assert "GitHub API error" in resp.json()["detail"]


def test_create_issue_with_labels(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(201, {"number": 9}))
    resp = client.post(
        "/api/github/repos/o/r/issues",
        json={"owner": "o", "repo": "r", "title": "T", "body": "B", "labels": ["bug"]},
    )
    assert resp.status_code == 200
    assert resp.json()["number"] == 9
    assert fake.calls[0][2] == {"title": "T", "body": "B", "labels": ["bug"]}


def test_create_issue_no_labels(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(201, {"number": 9}))
    resp = client.post(
        "/api/github/repos/o/r/issues",
        json={"owner": "o", "repo": "r", "title": "T"},
    )
    assert resp.status_code == 200
    assert fake.calls[0][2] == {"title": "T", "body": ""}


def test_trigger_workflow_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(204, None))
    resp = client.post(
        "/api/github/repos/o/r/actions/workflows/ci.yml/dispatches",
        json={"owner": "o", "repo": "r", "workflow_id": "ci.yml", "ref": "dev", "inputs": {"x": "y"}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": 204}


def test_trigger_workflow_failed(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(400, None, "bad ref"))
    resp = client.post(
        "/api/github/repos/o/r/actions/workflows/ci.yml/dispatches",
        json={"owner": "o", "repo": "r", "workflow_id": "ci.yml"},
    )
    assert resp.status_code == 400
    assert "Workflow dispatch failed" in resp.json()["detail"]


def test_search_repos_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"total_count": 1}))
    resp = client.get("/api/github/search/repos", params={"q": "raven", "page": 1, "per_page": 5})
    assert resp.status_code == 200
    assert resp.json() == {"total_count": 1}
    assert fake.calls[0][2] == {"q": "raven", "page": 1, "per_page": 5}


def test_search_repos_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/search/repos", params={"q": "raven"})
    assert resp.status_code == 401


def test_rate_limit(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"resources": {}}))
    resp = client.get("/api/github/rate-limit")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/rate_limit"


def test_rate_limit_error(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(500, None, "nope"))
    resp = client.get("/api/github/rate-limit")
    assert resp.status_code == 500


def test_file_tree(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(
        FakeResp(
            200,
            [
                {"name": "a.py", "path": "a.py", "type": "file", "size": 3},
                {"name": "src", "path": "src", "type": "dir", "size": 0},
            ],
        )
    )
    fake.add(FakeResp(200, [{"name": "b.py", "path": "src/b.py", "type": "file", "size": 5}]))
    resp = client.get("/api/github/repos/o/r/contents/tree", params={"ref": "dev"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["path"] == "a.py"
    assert body[1]["path"] == "src"
    assert body[2]["path"] == "src/b.py"
    assert fake.calls[1][2] == {"ref": "dev"}


def test_file_tree_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/repos/o/r/contents/tree")
    assert resp.status_code == 401


def test_file_tree_bad_status(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(500, None, "err"))
    resp = client.get("/api/github/repos/o/r/contents/tree")
    assert resp.status_code == 200
    assert resp.json() == []


def test_file_tree_non_list(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"message": "not a dir"}))
    resp = client.get("/api/github/repos/o/r/contents/tree")
    assert resp.status_code == 200
    assert resp.json() == []


def test_clone_repo_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.post("/api/github/repos/o/r/clone", json={"owner": "o", "repo": "r"})
    assert resp.status_code == 401


def test_clone_repo_access_denied(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, _, _ = env
    resp = client.post(
        "/api/github/repos/o/r/clone",
        json={"owner": "o", "repo": "r", "target_dir": "C:\\windows\\system32"},
    )
    assert resp.status_code == 403


def test_clone_repo_existing(env: tuple[TestClient, FakeClient, FakeSecrets], tmp_path: Path) -> None:
    client, fake, _ = env
    target = tmp_path / "clones" / "o" / "r"
    target.mkdir(parents=True)
    resp = client.post(
        "/api/github/repos/o/r/clone",
        json={"owner": "o", "repo": "r", "target_dir": str(tmp_path / "clones")},
    )
    assert resp.status_code == 200
    assert resp.json()["existing"] is True
    assert fake.calls == []


@pytest.mark.parametrize(
    ("returncode", "expected", "marker"),
    [(0, 200, "ok"), (1, 500, "Clone failed")],
)
def test_clone_repo_subprocess(
    env: tuple[TestClient, FakeClient, FakeSecrets],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    expected: int,
    marker: str,
) -> None:
    client, _, _ = env

    async def fake_exec(*args: Any, **kwargs: Any) -> FakeProc:
        return FakeProc(returncode, b"git error")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    target = tmp_path / "clones2"
    resp = client.post(
        "/api/github/repos/o/r/clone",
        json={"owner": "o", "repo": "r", "target_dir": str(target)},
    )
    assert resp.status_code == expected
    body = resp.json()
    if expected == 200:
        assert body["ok"] is True
    else:
        assert marker in body["detail"]


def test_clone_repo_git_missing(
    env: tuple[TestClient, FakeClient, FakeSecrets], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = env

    async def fake_exec(*args: Any, **kwargs: Any) -> FakeProc:
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    resp = client.post(
        "/api/github/repos/o/r/clone",
        json={"owner": "o", "repo": "r", "target_dir": str(tmp_path / "clones3")},
    )
    assert resp.status_code == 500
    assert "Git not found" in resp.json()["detail"]


def test_merge_pr_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"merged": True}))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/merge",
        json={"owner": "o", "repo": "r", "pull_number": 5, "commit_title": "CT", "commit_message": "CM"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"merged": True}
    payload = fake.calls[0][2]
    assert payload["merge_method"] == "merge"
    assert payload["commit_title"] == "CT"
    assert payload["commit_message"] == "CM"


def test_merge_pr_minimal(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"merged": False}))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/merge",
        json={"owner": "o", "repo": "r", "pull_number": 5},
    )
    assert resp.status_code == 200
    assert fake.calls[0][2] == {"merge_method": "merge"}


def test_merge_pr_failed(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(409, None, "conflict"))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/merge",
        json={"owner": "o", "repo": "r", "pull_number": 5},
    )
    assert resp.status_code == 409
    assert "Merge failed" in resp.json()["detail"]


def test_create_review_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"id": 11}))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/reviews",
        json={"owner": "o", "repo": "r", "pull_number": 5, "body": "LGTM", "event": "APPROVE", "commit_id": "abc"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == 11
    assert fake.calls[0][2] == {"body": "LGTM", "event": "APPROVE", "commit_id": "abc"}


def test_create_review_minimal(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"id": 12}))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/reviews",
        json={"owner": "o", "repo": "r", "pull_number": 5, "body": "x"},
    )
    assert resp.status_code == 200
    assert fake.calls[0][2] == {"body": "x", "event": "COMMENT"}


def test_create_review_failed(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(422, None, "bad"))
    resp = client.post(
        "/api/github/repos/o/r/pulls/5/reviews",
        json={"owner": "o", "repo": "r", "pull_number": 5},
    )
    assert resp.status_code == 422
    assert "Review failed" in resp.json()["detail"]


def test_list_reviews(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"id": 1}]))
    resp = client.get("/api/github/repos/o/r/pulls/5/reviews")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/pulls/5/reviews"


def test_list_issue_comments(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, [{"id": 2}]))
    resp = client.get("/api/github/repos/o/r/issues/5/comments")
    assert resp.status_code == 200
    assert fake.calls[0][1] == "https://api.github.com/repos/o/r/issues/5/comments"


def test_create_issue_comment(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(201, {"id": 3}))
    resp = client.post("/api/github/repos/o/r/issues/5/comments", json={"body": "hello"})
    assert resp.status_code == 200
    assert resp.json()["id"] == 3
    assert fake.calls[0][2] == {"body": "hello"}


def test_search_code_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(200, {"items": []}))
    resp = client.get("/api/github/repos/o/r/search/code", params={"q": "import os"})
    assert resp.status_code == 200
    assert fake.calls[0][2]["q"] == "repo:o/r import os"


def test_search_code_forbidden(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, fake, _ = env
    fake.add(FakeResp(403, None, "forbidden"))
    resp = client.get("/api/github/repos/o/r/search/code", params={"q": "x"})
    assert resp.status_code == 403
    assert "Code search requires" in resp.json()["detail"]


def test_search_code_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/repos/o/r/search/code", params={"q": "x"})
    assert resp.status_code == 401


def test_token_status_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _no_token(monkeypatch, tmp_path)
    resp = client.get("/api/github/token/status")
    assert resp.status_code == 200
    assert resp.json() == {"has_env_token": False, "has_oauth_token": False, "configured": False}


def test_token_status_env(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, _, secrets = env
    resp = client.get("/api/github/token/status")
    body = resp.json()
    assert body["has_env_token"] is True
    assert body["configured"] is True
    secrets.store["github_oauth_token"] = "oauth-tok"
    resp2 = client.get("/api/github/token/status")
    assert resp2.json()["has_oauth_token"] is True


def test_token_status_oauth_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gh, "_client", lambda: FakeClient())
    secrets = FakeSecrets()
    secrets.store["github_oauth_token"] = "oauth-tok"
    monkeypatch.setattr(
        gh, "settings", SimpleNamespace(github_token=FakeSecret(""), resolved_workspace=str(tmp_path))
    )
    monkeypatch.setattr(gh, "secrets", secrets)
    app = FastAPI()
    app.include_router(gh.create_github_router())
    client = TestClient(app)
    resp = client.get("/api/github/token/status")
    body = resp.json()
    assert body["has_env_token"] is False
    assert body["has_oauth_token"] is True
    assert body["configured"] is True


def test_set_github_token_empty(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, _, _ = env
    resp = client.post("/api/github/token", json={"token": "   "})
    assert resp.status_code == 400


def test_set_github_token_ok(env: tuple[TestClient, FakeClient, FakeSecrets]) -> None:
    client, _, secrets = env
    resp = client.post("/api/github/token", json={"token": "  ghp_new  "})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert secrets.store["github_oauth_token"] == "ghp_new"


def test_resolve_token_oauth_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secrets = FakeSecrets()
    secrets.store["github_oauth_token"] = "oauth-fallback"
    monkeypatch.setattr(
        gh, "settings", SimpleNamespace(github_token=FakeSecret(""), resolved_workspace=str(tmp_path))
    )
    monkeypatch.setattr(gh, "secrets", secrets)
    assert gh._resolve_token() == "oauth-fallback"
