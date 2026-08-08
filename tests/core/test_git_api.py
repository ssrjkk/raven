from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.coding.git_integration import GitIntegration
from raven.core.git_api import _parse_diff, create_git_router


def _git(r: Path, *args: str) -> tuple[str, str]:
    p = subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True)
    return p.stdout.strip(), p.stderr.strip()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, TestClient]:
    ws = tmp_path / "ws"
    ws.mkdir()
    r = ws / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    (r / "a.txt").write_text("line1\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "initial commit")
    (r / "b.txt").write_text("b1\n", encoding="utf-8")
    (r / "a.txt").write_text("line1\nline2\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "second commit")
    _git(r, "checkout", "-b", "feature")
    monkeypatch.setattr("raven.core.git_api.settings", SimpleNamespace(resolved_workspace=str(ws)))
    app = FastAPI()
    app.include_router(create_git_router())
    client = TestClient(app)
    return r, client


def test_status(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    resp = client.get("/api/git/status", params={"repo": str(r)})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_branch(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.get("/api/git/branch", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["branch"] == "feature"
    assert body["is_branch"] is True
    assert body["is_repo"] is True


def test_branches(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.get("/api/git/branches", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert "main" in body["branches"]
    assert "feature" in body["branches"]
    assert body["current"] == "feature"


def test_log(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.get("/api/git/log", params={"repo": str(r), "count": 5})
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert entries[0]["message"] == "second commit"


def test_log_detail(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    head = _git(r, "rev-parse", "--short", "HEAD")[0]
    resp = client.get(f"/api/git/log/detail/{head}", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hash"] == head
    assert body["message"] == "second commit"
    assert body["total_files"] >= 2
    assert body["total_added"] > 0
    assert "diff" in body


def test_log_detail_not_found(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(*args: str) -> tuple[str, str]:
        return ("abc", "")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.get("/api/git/log/detail/zzz", params={"repo": str(r)})
    assert resp.status_code == 200
    assert resp.json()["error"] == "commit not found"


def test_log_detail_binary_stats(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(self: object, *args: str) -> tuple[str, str]:
        if args[0] == "log":
            return ("h1|h|msg|an|ae|2026-01-01|2026-01-01T00:00:00+00:00|HEAD", "")
        if args[0] == "diff-tree":
            return ("-\t-\tfile.bin\n1\t1\tfile.py", "")
        return ("", "")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.get("/api/git/log/detail/abc", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_added"] == 1
    assert body["total_deleted"] == 1
    assert body["files"][0]["added"] == 0


def test_diff_staged(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "c.txt").write_text("c1\n", encoding="utf-8")
    _git(r, "add", "c.txt")
    resp = client.get("/api/git/diff", params={"repo": str(r), "staged": "true"})
    assert resp.status_code == 200
    assert "c.txt" in resp.json()["diff"]


def test_diff_unstaged(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "a.txt").write_text("line1\nchanged\n", encoding="utf-8")
    resp = client.get("/api/git/diff", params={"repo": str(r)})
    assert resp.status_code == 200
    assert "changed" in resp.json()["diff"]


def test_diff_commit(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    head = _git(r, "rev-parse", "--short", "HEAD")[0]
    resp = client.get(f"/api/git/diff/commit/{head}", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["diff"]
    assert len(body["files"]) >= 1
    assert body["files"][0]["added"] >= 0


def test_blame(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.get("/api/git/blame", params={"repo": str(r), "file": "a.txt"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["lines"]) >= 1
    assert body["lines"][0]["author"] == "Test"


def test_blame_fatal(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(*args: str) -> tuple[str, str]:
        return ("", "fatal: unknown revision")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.get("/api/git/blame", params={"repo": str(r), "file": "nope.txt"})
    assert resp.status_code == 200
    body = resp.json()
    assert "fatal" in body["error"]
    assert body["lines"] == []


def test_commit(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "c.txt").write_text("c1\n", encoding="utf-8")
    _git(r, "add", "c.txt")
    resp = client.post("/api/git/commit", params={"repo": str(r), "message": "add c"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["commit_hash"]


def test_commit_nothing_to_commit(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(self: object, *args: str) -> tuple[str, str]:
        return ("", "nothing to commit, working tree clean")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.post("/api/git/commit", params={"repo": str(r), "message": "nope"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_commit_auto(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "d.txt").write_text("d1\n", encoding="utf-8")
    resp = client.post("/api/git/commit", params={"repo": str(r), "auto": "true"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_push(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(self: object, *args: str) -> tuple[str, str]:
        return ("", "fatal: no configured push destination")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.post("/api/git/push", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "fatal" in body["output"]


def test_pull_error(repo: tuple[Path, TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    r, client = repo

    def fake_run(self: object, *args: str) -> tuple[str, str]:
        return ("", "error: cannot pull")

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    resp = client.post("/api/git/pull", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body["output"]


def test_checkout_create(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.post("/api/git/checkout", params={"repo": str(r), "branch": "newfeat", "create": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["branch"] == "newfeat"
    assert _git(r, "rev-parse", "--abbrev-ref", "HEAD")[0] == "newfeat"


def test_checkout_existing(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.post("/api/git/checkout", params={"repo": str(r), "branch": "main"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert _git(r, "rev-parse", "--abbrev-ref", "HEAD")[0] == "main"


def test_pr_not_feature_branch(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    _git(r, "checkout", "main")
    resp = client.post("/api/git/pr", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "Not on a feature branch" in body["error"]


def test_pr_push_failure(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.post("/api/git/pr", params={"repo": str(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"]


def test_review_no_diff(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    resp = client.post("/api/git/review", params={"repo": str(r)})
    assert resp.status_code == 200
    assert resp.json()["summary"] == "No diff to review"


def test_review_with_comments(repo: tuple[Path, TestClient]) -> None:
    r, client = repo
    (r / "a.txt").write_text("line1\n" + "x" * 250 + "\nprint('hi')\n", encoding="utf-8")
    resp = client.post("/api/git/review", params={"repo": str(r), "file_path": "a.txt"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]
    assert any(c["severity"] == "warning" for c in body["comments"])


def test_parse_diff_utility() -> None:
    diff = (
        "diff --git a/file.txt b/file.txt\n"
        "index 123..456\n"
        "@@ -1,3 +1,4 @@\n"
        " context\n"
        "+added line\n"
        "-removed line\n"
        "@@ -10 +12 @@\n"
        "+only\n"
    )
    parsed = _parse_diff(diff)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "file.txt"
    assert parsed[0]["added"] == 2
    assert parsed[0]["deleted"] == 1
    assert len(parsed[0]["hunks"]) == 2
    assert parsed[0]["hunks"][0]["new_start"] == 1
    assert parsed[0]["hunks"][1]["new_start"] == 12


def test_parse_diff_no_path_header() -> None:
    parsed = _parse_diff("diff --git a/x\n@@ -1 +1 @@\n+hello\n")
    assert len(parsed) == 1
    assert parsed[0]["path"] == "diff --git a/x"
    assert parsed[0]["added"] == 1
    assert parsed[0]["deleted"] == 0
