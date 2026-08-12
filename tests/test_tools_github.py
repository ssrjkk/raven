from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

import raven.tools.github as github
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.github import (
    _github_api,
    _resolve_oauth_token,
    github_clone_repo,
    github_create_comment,
    github_create_issue,
    github_create_pr,
    github_create_review,
    github_get_file,
    github_get_pr_files,
    github_get_repo,
    github_list_branches,
    github_list_comments,
    github_list_pulls,
    github_list_repos,
    github_merge_pr,
    github_search_code,
    github_search_repos,
    github_trigger_workflow,
    register_github_tools,
)


class _Token:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _Resp:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._json


class _Client:
    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def _next(self) -> _Resp:
        return self._responses.pop(0)

    async def get(self, url: str) -> _Resp:
        self.calls.append(("GET", url, None))
        return self._next()

    async def post(self, url: str, json: Any = None) -> _Resp:
        self.calls.append(("POST", url, json))
        return self._next()

    async def put(self, url: str, json: Any = None) -> _Resp:
        self.calls.append(("PUT", url, json))
        return self._next()

    async def request(self, method: str, url: str, json: Any = None) -> _Resp:
        self.calls.append((method, url, json))
        return self._next()

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _Proc:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", self._stderr)


def _set_token(monkeypatch: pytest.MonkeyPatch, value: str = "ghp_test") -> None:
    monkeypatch.setattr(github, "settings", SimpleNamespace(github_token=_Token(value)))


def _install_client(monkeypatch: pytest.MonkeyPatch, *responses: _Resp) -> _Client:
    client = _Client(*responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: client)
    return client


class TestGithubApi:
    async def test_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        result = await _github_api("GET", "/user/repos")
        assert isinstance(result, dict)
        assert "GitHub token not configured" in result["error"]

    async def test_get_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"id": 1, "name": "r"}))
        result = await _github_api("GET", "/user/repos")
        assert result == {"id": 1, "name": "r"}
        assert client.calls == [("GET", "https://api.github.com/user/repos", None)]

    async def test_get_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(200, [{"id": 1}]))
        result = await _github_api("GET", "/user/repos")
        assert result == [{"id": 1}]

    async def test_post_uses_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(201, {"id": 5}))
        result = await _github_api("POST", "/repos/o/r/pulls", {"title": "t"})
        assert result == {"id": 5}
        assert client.calls == [("POST", "https://api.github.com/repos/o/r/pulls", {"title": "t"})]

    async def test_unauthorized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(401, {"message": "bad"}, "Bad credentials"))
        result = await _github_api("GET", "/user")
        assert isinstance(result, dict)
        assert "invalid or expired" in result["error"]

    async def test_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(404, None, "Not Found"))
        result = await _github_api("GET", "/user")
        assert isinstance(result, dict)
        assert "404" in result["error"]
        assert "Not Found" in result["error"]


class TestGithubListRepos:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, [{"name": "a"}]))
        result = await github_list_repos(page=2, per_page=5, sort="pushed")
        assert result == [{"name": "a"}]
        assert "/user/repos?page=2&per_page=5&sort=pushed&type=owner" in client.calls[0][1]


class TestGithubGetRepo:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"full_name": "o/r"}))
        result = await github_get_repo("o", "r")
        assert result == {"full_name": "o/r"}
        assert "/repos/o/r" in client.calls[0][1]


class TestGithubListBranches:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, [{"name": "main"}]))
        result = await github_list_branches("o", "r")
        assert result == [{"name": "main"}]
        assert "/repos/o/r/branches" in client.calls[0][1]


class TestGithubListPulls:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, [{"number": 1}]))
        result = await github_list_pulls("o", "r", state="closed")
        assert result == [{"number": 1}]
        assert "/repos/o/r/pulls?state=closed&sort=updated&direction=desc" in client.calls[0][1]


class TestGithubGetFile:
    async def test_without_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"content": "eA=="}))
        result = await github_get_file("o", "r", "src/main.py")
        assert result == {"content": "eA=="}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/contents/src/main.py"

    async def test_with_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"content": "eA=="}))
        result = await github_get_file("o", "r", "src/main.py", ref="dev")
        assert result == {"content": "eA=="}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/contents/src/main.py?ref=dev"


class TestGithubCreatePr:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(201, {"number": 7, "title": "t"}))
        result = await github_create_pr("o", "r", "t", body="b", head="feat", base="main")
        assert result == {"number": 7, "title": "t"}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/pulls"
        assert client.calls[0][2] == {"title": "t", "body": "b", "head": "feat", "base": "main"}

    async def test_result_without_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(201, [{"number": 7}]))
        result = await github_create_pr("o", "r", "t")
        assert result == [{"number": 7}]


class TestGithubCreateIssue:
    async def test_with_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(201, {"number": 3, "title": "i"}))
        result = await github_create_issue("o", "r", "i", body="d", labels=["bug"])
        assert result == {"number": 3, "title": "i"}
        assert client.calls[0][2] == {"title": "i", "body": "d", "labels": ["bug"]}

    async def test_without_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(201, {"number": 4}))
        result = await github_create_issue("o", "r", "i")
        assert result == {"number": 4}
        assert client.calls[0][2] == {"title": "i", "body": ""}


class TestGithubSearchRepos:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"items": [{"name": "a"}]}))
        result = await github_search_repos("raven", page=1, per_page=5)
        assert result == {"items": [{"name": "a"}]}
        assert "/search/repositories?q=raven&page=1&per_page=5" in client.calls[0][1]


class TestGithubGetPrFiles:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, [{"filename": "a.py"}]))
        result = await github_get_pr_files("o", "r", 7)
        assert result == [{"filename": "a.py"}]
        assert "/repos/o/r/pulls/7/files" in client.calls[0][1]


class TestGithubTriggerWorkflow:
    async def test_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        result = await github_trigger_workflow("o", "r", "ci.yml")
        assert isinstance(result, dict)
        assert "GitHub token not configured" in result["error"]

    async def test_dispatched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(204))
        result = await github_trigger_workflow("o", "r", "ci.yml", ref="main", inputs={"k": "v"})
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert "ci.yml" in result["message"]
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/actions/workflows/ci.yml/dispatches"
        assert client.calls[0][2] == {"ref": "main", "inputs": {"k": "v"}}

    async def test_dispatched_default_inputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(204))
        result = await github_trigger_workflow("o", "r", "ci.yml")
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert client.calls[0][2] == {"ref": "main", "inputs": {}}

    async def test_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(422, None, "Bad request"))
        result = await github_trigger_workflow("o", "r", "ci.yml")
        assert isinstance(result, dict)
        assert "422" in result["error"]
        assert "Bad request" in result["error"]


class TestGithubMergePr:
    async def test_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "")
        result = await github_merge_pr("o", "r", 7)
        assert isinstance(result, dict)
        assert "GitHub token not configured" in result["error"]

    async def test_oauth_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "oauth-token")
        client = _install_client(monkeypatch, _Resp(200, {"merged": True}))
        result = await github_merge_pr("o", "r", 7)
        assert result == {"merged": True}
        assert client.calls[0][0] == "PUT"

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"merged": True, "sha": "abc"}))
        result = await github_merge_pr("o", "r", 7, merge_method="squash")
        assert result == {"merged": True, "sha": "abc"}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/pulls/7/merge"
        assert client.calls[0][2] == {"merge_method": "squash"}

    async def test_merge_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(409, None, "conflict"))
        result = await github_merge_pr("o", "r", 7)
        assert isinstance(result, dict)
        assert "Merge failed" in result["error"]
        assert "conflict" in result["error"]


class TestGithubCreateReview:
    async def test_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "")
        result = await github_create_review("o", "r", 7)
        assert isinstance(result, dict)
        assert "GitHub token not configured" in result["error"]

    async def test_oauth_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "oauth-token")
        client = _install_client(monkeypatch, _Resp(200, {"id": 1}))
        result = await github_create_review("o", "r", 7, body="lgtm", event="APPROVE")
        assert result == {"id": 1}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/pulls/7/reviews"
        assert client.calls[0][2] == {"body": "lgtm", "event": "APPROVE"}

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"id": 2, "state": "APPROVED"}))
        result = await github_create_review("o", "r", 7)
        assert result == {"id": 2, "state": "APPROVED"}
        assert client.calls[0][2] == {"body": "", "event": "COMMENT"}

    async def test_review_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        _install_client(monkeypatch, _Resp(422, None, "invalid event"))
        result = await github_create_review("o", "r", 7)
        assert isinstance(result, dict)
        assert "Review failed" in result["error"]
        assert "invalid event" in result["error"]


class TestGithubListComments:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, [{"body": "hi"}]))
        result = await github_list_comments("o", "r", 7)
        assert result == [{"body": "hi"}]
        assert "/repos/o/r/issues/7/comments" in client.calls[0][1]


class TestGithubCreateComment:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(201, {"id": 9}))
        result = await github_create_comment("o", "r", 7, "nice")
        assert result == {"id": 9}
        assert client.calls[0][1] == "https://api.github.com/repos/o/r/issues/7/comments"
        assert client.calls[0][2] == {"body": "nice"}


class TestGithubSearchCode:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_token(monkeypatch)
        client = _install_client(monkeypatch, _Resp(200, {"items": [{"path": "a.py"}]}))
        result = await github_search_code("o", "r", "def main", page=1, per_page=5)
        assert result == {"items": [{"path": "a.py"}]}
        assert "/search/code?q=repo:o/r+def main&page=1&per_page=5" in client.calls[0][1]


class TestGithubCloneRepo:
    async def test_missing_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "")
        monkeypatch.chdir(tmp_path)
        result = await github_clone_repo("o", "r")
        assert isinstance(result, dict)
        assert "GitHub token not configured" in result["error"]

    async def test_existing_target(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch)
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "workspace" / "cloned" / "o" / "r"
        target.mkdir(parents=True)
        result = await github_clone_repo("o", "r")
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert result["existing"] is True
        assert "cloned" in result["path"]

    async def test_oauth_fallback_existing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch, "")
        monkeypatch.setattr(github, "_resolve_oauth_token", lambda: "oauth-token")
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "workspace" / "cloned" / "o" / "r"
        target.mkdir(parents=True)
        result = await github_clone_repo("o", "r")
        assert isinstance(result, dict)
        assert result["existing"] is True

    async def test_clone_success(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=_Proc(returncode=0)))
        result = await github_clone_repo("o", "r", branch="dev")
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert "workspace" in result["path"]

    async def test_clone_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=_Proc(returncode=1, stderr=b"boom")))
        result = await github_clone_repo("o", "r")
        assert isinstance(result, dict)
        assert "Clone failed" in result["error"]
        assert "boom" in result["error"]

    async def test_git_not_found(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _set_token(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError))
        result = await github_clone_repo("o", "r")
        assert isinstance(result, dict)
        assert "Git not found" in result["error"]


class TestResolveOauthToken:
    def test_returns_stored_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "raven.core.secrets.secrets",
            SimpleNamespace(get=lambda key, default: "oauth-token" if key == "github_oauth_token" else default),
        )
        assert _resolve_oauth_token() == "oauth-token"

    def test_returns_empty_on_import_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "raven.core.secrets", None)
        assert _resolve_oauth_token() == ""


class TestRegisterGithubTools:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        register_github_tools(registry)
        names = [
            "github_list_repos",
            "github_get_repo",
            "github_list_branches",
            "github_list_pulls",
            "github_get_file",
            "github_create_pr",
            "github_create_issue",
            "github_search_repos",
            "github_get_pr_files",
            "github_trigger_workflow",
            "github_merge_pr",
            "github_create_review",
            "github_list_comments",
            "github_create_comment",
            "github_search_code",
            "github_clone_repo",
        ]
        for name in names:
            assert registry.get(name) is not None

