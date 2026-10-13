from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import aios.api.bridge as bridge
from aios.agents.orchestrator import Orchestrator
from raven.cli.aios_cmd import create_aios_app
from raven.core.auth.tokens import token_manager
from ravencode.agents.orchestrator import AgentType
from ravencode.api.client import AIResponse

# ─── aios.agents.Orchestrator: exception fallback ────────────────────


@pytest.mark.asyncio
async def test_orchestrator_dispatch_exception_returns_error_dict() -> None:
    orch = Orchestrator()
    with patch.object(orch._inner, "dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.side_effect = RuntimeError("inner failed")
        result = await orch.dispatch("task", AgentType.AUTONOMOUS)
    assert result["success"] is False
    assert "inner failed" in result["error"]
    assert result["agent"] == AgentType.AUTONOMOUS.value


# ─── _compute_confirm_diff ───────────────────────────────────────────


class TestComputeConfirmDiff:
    def test_missing_path_returns_none(self) -> None:
        assert bridge._compute_confirm_diff("write_file", {}) is None

    def test_read_exception_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _BoomPath:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def is_absolute(self) -> bool:
                return True

            def is_file(self) -> bool:
                raise OSError("disk on fire")

        monkeypatch.setattr(bridge, "Path", _BoomPath)
        assert bridge._compute_confirm_diff("write_file", {"path": "x"}) is None

    def test_write_file_diff(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("old\n", encoding="utf-8")
        diff = bridge._compute_confirm_diff("write_file", {"path": str(target), "content": "new\n"})
        assert diff is not None
        assert "-old" in diff
        assert "+new" in diff

    def test_relative_path_resolves_against_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "r.txt").write_text("a\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        diff = bridge._compute_confirm_diff("write", {"path": "r.txt", "content": "b\n"})
        assert diff is not None
        assert "-a" in diff
        assert "+b" in diff

    def test_edit_exact_substring_match(self, tmp_path: Path) -> None:
        target = tmp_path / "e.txt"
        target.write_text("hello world\n", encoding="utf-8")
        diff = bridge._compute_confirm_diff(
            "edit_file",
            {"file_path": str(target), "old_string": "hello", "new_string": "bye"},
        )
        assert diff is not None
        assert "-hello world" in diff
        assert "+bye world" in diff

    def test_edit_whitespace_fuzzy_match(self, tmp_path: Path) -> None:
        target = tmp_path / "fuzzy.txt"
        # trailing whitespace so exact `in` fails, but block-line compare after rstrip succeeds
        target.write_text("foo   \nbar   \n", encoding="utf-8")
        diff = bridge._compute_confirm_diff(
            "edit",
            {"file": str(target), "old_string": "foo\nbar", "new_string": "X\nY"},
        )
        assert diff is not None
        assert "+X" in diff
        assert "+Y" in diff

    def test_edit_old_string_not_found_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "n.txt"
        target.write_text("alpha\nbeta\n", encoding="utf-8")
        result = bridge._compute_confirm_diff(
            "edit_file",
            {"path": str(target), "old_string": "gamma\ndelta", "new_string": "x"},
        )
        assert result is None

    def test_smart_edit_uses_new_content(self, tmp_path: Path) -> None:
        target = tmp_path / "s.txt"
        target.write_text("first\n", encoding="utf-8")
        diff = bridge._compute_confirm_diff("smart_edit", {"path": str(target), "new_content": "second\n"})
        assert diff is not None
        assert "+second" in diff

    def test_smart_edit_falls_back_to_content(self, tmp_path: Path) -> None:
        target = tmp_path / "s2.txt"
        target.write_text("a\n", encoding="utf-8")
        diff = bridge._compute_confirm_diff("smart_edit", {"path": str(target), "content": "b\n"})
        assert diff is not None

    def test_patch_file_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "p.txt"
        target.write_text("a\n", encoding="utf-8")
        assert bridge._compute_confirm_diff("patch_file", {"path": str(target), "content": "b"}) is None

    def test_identical_content_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "same.txt"
        target.write_text("hello\n", encoding="utf-8")
        assert bridge._compute_confirm_diff("write_file", {"path": str(target), "content": "hello\n"}) is None

    def test_new_file_when_missing_on_disk(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.txt"
        diff = bridge._compute_confirm_diff("write_file", {"path": str(target), "content": "brand new\n"})
        assert diff is not None
        assert "+brand new" in diff


# ─── _session_read ───────────────────────────────────────────────────


def _mk_session(tmp_path: Path, sid: str, content: str) -> Path:
    d = tmp_path / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.json"
    p.write_text(content, encoding="utf-8")
    return p


class TestSessionRead:
    def test_invalid_id_returns_none(self) -> None:
        assert bridge._session_read("bad id with spaces") is None

    def test_missing_file_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert bridge._session_read("nope") is None

    def test_valid_session_populates_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mk_session(tmp_path, "abc", json.dumps({"messages": ["hi"]}))
        monkeypatch.chdir(tmp_path)
        data = bridge._session_read("abc")
        assert data is not None
        assert data["id"] == "abc"
        assert data["messages"] == ["hi"]

    def test_non_dict_json_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mk_session(tmp_path, "abc", "[1, 2, 3]")
        monkeypatch.chdir(tmp_path)
        assert bridge._session_read("abc") is None

    def test_bad_json_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mk_session(tmp_path, "abc", "{not json")
        monkeypatch.chdir(tmp_path)
        assert bridge._session_read("abc") is None


# ─── _rg_search ──────────────────────────────────────────────────────


class _Proc:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout


class TestRgSearch:
    def test_ripgrep_parses_match_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        match = {
            "type": "match",
            "data": {
                "path": {"text": str(tmp_path / "a.py")},
                "line_number": 2,
                "lines": {"text": "hello\n"},
            },
        }
        context = {"type": "context"}
        stdout = "\n".join([json.dumps(match), json.dumps(context), "not-json"])
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(stdout=stdout))
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/rg")
        results = bridge._rg_search("hello", tmp_path, limit=10)
        assert results == [{"file": "a.py", "line": 2, "text": "hello"}]

    def test_ripgrep_exception_falls_back_to_python(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "x.txt").write_text("needle here\n", encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/rg")

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("rg exploded")

        monkeypatch.setattr(subprocess, "run", _boom)
        results = bridge._rg_search("needle", tmp_path, limit=10)
        assert results and results[0]["file"] == "x.txt"

    def test_python_fallback_when_no_ripgrep(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "f.py").write_text("alpha\nbeta gamma\n", encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: None)
        results = bridge._rg_search("beta", tmp_path, limit=10)
        assert results == [{"file": "f.py", "line": 2, "text": "beta gamma"}]

    def test_python_fallback_respects_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for i in range(5):
            (tmp_path / f"file{i}.txt").write_text(f"match {i}\n", encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: None)
        results = bridge._rg_search("match", tmp_path, limit=2)
        assert len(results) == 2

    def test_python_fallback_skips_unreadable_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "bad.txt").write_text("ok", encoding="utf-8")
        (tmp_path / "good.txt").write_text("other\n", encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: None)
        original_read_text = Path.read_text

        def _maybe_boom(self: Path, *a: Any, **k: Any) -> str:
            if self.name == "bad.txt":
                raise OSError("no")
            return original_read_text(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", _maybe_boom)
        results = bridge._rg_search("ok", tmp_path, limit=5)
        assert results == []

    def test_python_fallback_skips_non_file_entries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "hit.txt").write_text("needle\n", encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: None)
        # yield a directory-like entry first (is_file() False) so the loop skips it
        monkeypatch.setattr(
            "ravencode.runtime.fs_walk.iter_files",
            lambda _root: iter([tmp_path, tmp_path / "hit.txt"]),
        )
        results = bridge._rg_search("needle", tmp_path, limit=10)
        assert results == [{"file": "hit.txt", "line": 1, "text": "needle"}]

    def test_python_fallback_breaks_within_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "many.txt").write_text("x\n" * 6, encoding="utf-8")
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: None)
        results = bridge._rg_search("x", tmp_path, limit=2)
        assert len(results) == 2

    def test_ripgrep_breaks_on_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        matches = [
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": str(tmp_path / "f.py")},
                        "line_number": i,
                        "lines": {"text": "hit\n"},
                    },
                }
            )
            for i in range(5)
        ]
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/rg")
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(stdout="\n".join(matches)))
        results = bridge._rg_search("hit", tmp_path, limit=2)
        assert len(results) == 2


# ─── route-level tests ───────────────────────────────────────────────


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_aios_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_h() -> dict[str, str]:
    token = token_manager.create_token("bridge-admin", "admin")
    return {"Authorization": f"Bearer {token}"}


def _confine_under(ws: Path):
    ws = ws.resolve()

    def _c(path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = ws / p
        p = p.resolve()
        try:
            p.relative_to(ws)
        except ValueError as exc:
            raise PermissionError(f"outside workspace {ws}") from exc
        return p

    return _c


class TestCompletionRoute:
    def test_empty_input_short_circuits(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.post("/aios/completion", json={}, headers=admin_h)
        assert resp.status_code == 200
        assert resp.json() == {"completion": ""}

    def test_plain_completion(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            return_value=AIResponse(text="print(1)", model="m", provider="p"),
        ):
            resp = client.post("/aios/completion", json={"prefix": "def f():"}, headers=admin_h)
        assert resp.json() == {"completion": "print(1)"}

    def test_fenced_completion_is_stripped(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            return_value=AIResponse(text="```python\nprint(1)\n```", model="m", provider="p"),
        ):
            resp = client.post(
                "/aios/completion",
                json={"prefix": "def f():", "suffix": "y", "language": "python"},
                headers=admin_h,
            )
        assert resp.json() == {"completion": "print(1)"}

    def test_exception_returns_error_payload(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post("/aios/completion", json={"prefix": "x"}, headers=admin_h)
        data = resp.json()
        assert data["completion"] == ""
        assert "error" in data


class TestInlineEditRoute:
    def test_missing_inputs_return_original(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.post("/aios/inline-edit", json={"code": "abc"}, headers=admin_h)
        assert resp.json() == {"edited_code": "abc", "diff": ""}

    def test_plain_edit(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            return_value=AIResponse(text="hello", model="m", provider="p"),
        ):
            resp = client.post("/aios/inline-edit", json={"code": "world", "instruction": "greet"}, headers=admin_h)
        data = resp.json()
        assert data["edited_code"] == "hello"
        assert "diff" in data

    def test_fenced_edit_stripped(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            return_value=AIResponse(text="```\nnew\n```", model="m", provider="p"),
        ):
            resp = client.post(
                "/aios/inline-edit",
                json={"code": "old", "instruction": "replace", "language": "text"},
                headers=admin_h,
            )
        assert resp.json()["edited_code"] == "new"

    def test_exception_returns_original(self, client: TestClient, admin_h: dict[str, str]) -> None:
        with patch(
            "ravencode.api.client.AIOSClient.ask",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post("/aios/inline-edit", json={"code": "keep", "instruction": "x"}, headers=admin_h)
        data = resp.json()
        assert data["edited_code"] == "keep"
        assert "error" in data


class TestWorkspaceTreeRoute:
    def test_outside_denied(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/tree", params={"path": str(tmp_path.parent)}, headers=admin_h)
        assert "Access denied" in resp.json()["error"]

    def test_not_a_dir(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "notdir.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/tree", params={"path": "notdir.txt"}, headers=admin_h)
        assert resp.json()["error"] == "Path is not a directory"

    def test_tree_filters_hidden_and_vendor(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        (ws / "sub").mkdir(parents=True)
        (ws / "a.py").write_text("a", encoding="utf-8")
        (ws / "sub" / "b.py").write_text("b", encoding="utf-8")
        (ws / ".hidden").write_text("skip", encoding="utf-8")
        (ws / "node_modules").mkdir()
        (ws / "node_modules" / "x.js").write_text("y", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/tree", params={"path": "."}, headers=admin_h)
        tree = resp.json()["tree"]
        names = [c["name"] for c in tree["children"]]
        assert "sub" in names and "a.py" in names
        assert ".hidden" not in names and "node_modules" not in names

    def test_tree_stops_past_max_depth(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        d = ws
        for i in range(8):
            d = d / f"l{i}"
            d.mkdir(parents=True)
        (d / "deep.txt").write_text("z", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/tree", params={"path": "."}, headers=admin_h)

        names: list[str] = []

        def _walk(node: dict[str, Any] | None) -> None:
            if not node:
                return
            names.append(node.get("name", ""))
            for child in node.get("children", []):
                _walk(child)

        _walk(resp.json()["tree"])
        assert "l4" in names  # recursion depth 5 is allowed
        assert "l5" not in names  # guard fires at depth > 5
        assert "deep.txt" not in names

    def test_tree_permission_error_returns_empty(
        self, client: TestClient, admin_h: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BoomDir:
            def is_dir(self) -> bool:
                return True

            def iterdir(self) -> Any:
                raise PermissionError("denied")

            def __str__(self) -> str:
                return "boom"

        monkeypatch.setattr(bridge, "confine", lambda _p: _BoomDir())
        resp = client.get("/aios/workspace/tree", params={"path": "."}, headers=admin_h)
        assert resp.json()["tree"] is None


class TestWorkspaceReadRoute:
    def test_outside_denied(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/read", params={"path": str(tmp_path.parent / "x")}, headers=admin_h)
        assert "Access denied" in resp.json()["error"]

    def test_not_a_file(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/read", params={"path": "."}, headers=admin_h)
        assert resp.json()["error"] == "File not found"

    def test_read_success(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "hello.txt").write_text("hi there", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/read", params={"path": "hello.txt"}, headers=admin_h)
        data = resp.json()
        assert data["content"] == "hi there"
        assert data["size"] == 8

    def test_undecodable_returns_error(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "bin.dat").write_bytes(b"\xff\xfe\x00invalid")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.get("/aios/workspace/read", params={"path": "bin.dat"}, headers=admin_h)
        assert resp.json()["error"] == "Failed to read file"


class TestWorkspaceWriteRoute:
    def test_missing_path(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.post("/aios/workspace/write", json={"content": "x"}, headers=admin_h)
        assert resp.json()["error"] == "Path required"

    def test_outside_denied(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post(
            "/aios/workspace/write", json={"path": str(tmp_path.parent / "x.txt"), "content": "y"}, headers=admin_h
        )
        assert "Access denied" in resp.json()["error"]

    def test_write_success(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post("/aios/workspace/write", json={"path": "sub/dir/new.txt", "content": "abc"}, headers=admin_h)
        data = resp.json()
        assert data["ok"] is True
        assert data["size"] == 3
        assert (ws / "sub" / "dir" / "new.txt").read_text(encoding="utf-8") == "abc"

    def test_write_error_when_target_is_directory(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        (ws / "occupied").mkdir(parents=True)
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post("/aios/workspace/write", json={"path": "occupied", "content": "x"}, headers=admin_h)
        assert resp.json()["error"] == "Failed to write file"


class TestSearchRoute:
    def test_missing_query(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.post("/aios/search", json={}, headers=admin_h)
        assert resp.json()["error"] == "Query required"

    def test_outside_denied(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post("/aios/search", json={"query": "x", "path": str(tmp_path.parent)}, headers=admin_h)
        assert "Access denied" in resp.json()["error"]

    def test_not_a_dir(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "f.txt").write_text("hi", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post("/aios/search", json={"query": "hi", "path": "f.txt"}, headers=admin_h)
        assert resp.json()["error"] == "Path is not a directory"

    def test_success_via_python_fallback(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "code.py").write_text("alpha\nneedle in a haystack\nomega\n", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        monkeypatch.setattr(shutil, "which", lambda _n: None)
        resp = client.post("/aios/search", json={"query": "needle", "path": "."}, headers=admin_h)
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["file"] == "code.py"
        assert data["results"][0]["line"] == 2


class TestSemanticSearchRoute:
    def test_missing_query(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.post("/aios/search/semantic", json={}, headers=admin_h)
        assert resp.json()["error"] == "Query required"

    def test_outside_denied(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post(
            "/aios/search/semantic",
            json={"query": "x", "path": str(tmp_path.parent)},
            headers=admin_h,
        )
        assert "Access denied" in resp.json()["error"]

    def test_not_a_dir(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "f.txt").write_text("hi", encoding="utf-8")
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        resp = client.post("/aios/search/semantic", json={"query": "hi", "path": "f.txt"}, headers=admin_h)
        assert resp.json()["error"] == "Path is not a directory"

    def test_success_shapes_results(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(bridge, "confine", _confine_under(ws))
        fake_index = type("FakeIndex", (), {"search": lambda self, _r, _q, k=0: ["mod.py:10-12\nfoo()\nbar()"]})()
        monkeypatch.setattr("ravencode.runtime.code_search.RepoIndex", lambda: fake_index)
        resp = client.post("/aios/search/semantic", json={"query": "x", "path": "."}, headers=admin_h)
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["file"] == "mod.py"
        assert data["results"][0]["range"] == "10-12"
        assert "foo()" in data["results"][0]["text"]


class TestSessionsRoutes:
    def test_list_sessions(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.get("/aios/sessions", headers=admin_h)
        assert resp.status_code == 200
        assert "sessions" in resp.json()

    def test_delete_missing_returns_false(self, client: TestClient, admin_h: dict[str, str]) -> None:
        resp = client.delete("/aios/sessions/nope-does-not-exist", headers=admin_h)
        assert resp.json() == {"deleted": False}

    def test_get_session_not_found(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        resp = client.get("/aios/sessions/ghost", headers=admin_h)
        assert resp.json() == {"error": "Session not found"}

    def test_get_session_found(
        self, client: TestClient, admin_h: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = tmp_path / "data" / "sessions"
        d.mkdir(parents=True)
        (d / "abc.json").write_text(json.dumps({"messages": ["hi"]}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        resp = client.get("/aios/sessions/abc", headers=admin_h)
        data = resp.json()
        assert data["id"] == "abc"
        assert data["messages"] == ["hi"]
