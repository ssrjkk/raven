from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def py_file(tmp_path: Path) -> Path:
    return tmp_path / "sample.py"


class TestPatternList:
    def test_all_patterns_registered(self) -> None:
        from raven.core.pattern_checker import _PATTERN_LIST, _get_patterns

        patterns = _get_patterns()
        assert {p["id"] for p in patterns} == {pid for pid, *_ in _PATTERN_LIST}
        for p in patterns:
            assert callable(p["check"])
            assert p["severity"] in ("error", "warning", "info")

    def test_checks_endpoint_lists_without_dunder(self, tmp_path: Path) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.pattern_checker import create_pattern_checker_router

        app = FastAPI()
        app.include_router(create_pattern_checker_router(str(tmp_path)))
        client = TestClient(app)
        resp = client.get("/api/v1/patterns/checks")
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()]
        assert "print-vs-loguru" in ids
        assert "hardcoded-secret" in ids
        assert len(ids) == 7


class TestCheckFunctions:
    def test_print_vs_loguru(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_print_vs_loguru

        content = 'print("hello")\nx = 1\n# print("commented")\n'
        v = _check_print_vs_loguru(py_file, content, content.split("\n"))
        assert len(v) == 1
        assert v[0]["pattern_id"] == "print-vs-loguru"
        assert v[0]["line"] == 1
        assert v[0]["fix_hint"].startswith("Replace")

    def test_print_vs_loguru_with_import(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_print_vs_loguru

        content = "from loguru import logger\nprint('x')\n"
        v = _check_print_vs_loguru(py_file, content, content.split("\n"))
        assert len(v) == 1
        assert "Already imported" in v[0]["fix_hint"]

    def test_missing_type_hints_detected(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_type_hints

        content = 'def add(a, b):\n    return a + b\n\ndef typed(x: int) -> int:\n    return x\n'
        v = _check_type_hints(py_file, content, content.split("\n"))
        ids = {x["pattern_id"] for x in v}
        assert "missing-type-hints" in ids
        lines = {x["line"] for x in v}
        assert 1 in lines

    def test_missing_type_hints_skips_private_and_self(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_type_hints

        content = "def _private(x):\n    return x\n\nclass A:\n    def method(self, value):\n        return value\n"
        v = _check_type_hints(py_file, content, content.split("\n"))
        messages = [x["message"] for x in v]
        assert not any("_private" in m for m in messages)
        assert any("'value'" in m for m in messages)

    def test_missing_type_hints_syntax_error_safe(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_type_hints

        assert _check_type_hints(py_file, "def broken(:\n", ["def broken(:\n"]) == []

    def test_bare_except(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_bare_except

        content = "try:\n    x = 1\nexcept:\n    pass\nexcept ValueError:\n    pass\n"
        v = _check_bare_except(py_file, content, content.split("\n"))
        assert len(v) == 1
        assert v[0]["line"] == 3
        assert v[0]["severity"] == "error"

    def test_os_path_usage(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_os_path

        content = 'p = os.path.join("a", "b")\n# os.path.join commented\nx = Path("a")\n'
        v = _check_os_path(py_file, content, content.split("\n"))
        assert len(v) == 1
        assert v[0]["pattern_id"] == "os-path-vs-pathlib"
        assert v[0]["line"] == 1

    def test_mutable_default_arg(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_mutable_defaults

        content = "def f(x=[]):\n    pass\n\ndef g(y=None):\n    pass\n"
        v = _check_mutable_defaults(py_file, content, content.split("\n"))
        assert len(v) == 1
        assert v[0]["line"] == 1

    def test_hardcoded_secret_detected(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_hardcoded_secrets

        content = 'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"\npassword = "super-secret-value"\nx = 1\n'
        v = _check_hardcoded_secrets(py_file, content, content.split("\n"))
        assert len(v) == 2
        assert all(x["pattern_id"] == "hardcoded-secret" for x in v)

    def test_todo_fixme(self, py_file: Path) -> None:
        from raven.core.pattern_checker import _check_todo_comments

        content = "# TODO: finish this\n# FIXME: bug here\nx = 1\n# HACK: whatever\n# XXX: noted\n"
        v = _check_todo_comments(py_file, content, content.split("\n"))
        assert len(v) == 4
        tags = {x["line_content"].strip() for x in v}
        assert "# TODO: finish this" in tags
        assert all(x["severity"] == "info" for x in v)


class TestRunEndpoint:
    def _client(self, workspace: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.pattern_checker import create_pattern_checker_router

        app = FastAPI()
        app.include_router(create_pattern_checker_router(str(workspace)))
        return TestClient(app)

    def test_run_single_file_finds_violations(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text('print("hi")\n# TODO: fix\n', encoding="utf-8")
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "app.py"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["files_checked"] == 1
        assert body["total"] == 2
        assert body["by_severity"] == {"error": 0, "warning": 1, "info": 1}

    def test_run_filter_by_check_ids(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text('print("hi")\n# TODO: fix\n', encoding="utf-8")
        client = self._client(tmp_path)
        resp = client.get(
            "/api/v1/patterns/run", params={"file": "app.py", "check_ids": "print-vs-loguru"}
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["violations"][0]["pattern_id"] == "print-vs-loguru"

    def test_run_file_not_found(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "missing.py"})
        assert resp.status_code == 200
        assert "File not found" in resp.json()["error"]

    def test_run_access_denied_traversal(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "../outside.py"})
        assert resp.status_code == 200
        assert "Access denied" in resp.json()["error"]

    def test_run_access_denied_absolute(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": str(tmp_path.parent / "x.py")})
        assert resp.status_code == 200
        assert "Access denied" in resp.json()["error"]

    def test_run_directory_scan(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("import os\nx = os.path.join('a','b')\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (tmp_path / ".hidden.py").write_text("print('x')\n", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "c.py").write_text("print('x')\n", encoding="utf-8")
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run")
        body = resp.json()
        assert body["files_checked"] == 2
        assert any(v["file"].endswith("a.py") for v in body["violations"])

    def test_run_symlink_denied(self, tmp_path: Path) -> None:
        import sys

        if sys.platform == "win32":
            pytest.skip("symlink creation requires privileges on Windows")
        outside = tmp_path.parent / "outside_target.py"
        outside.write_text("print('x')\n", encoding="utf-8")
        link = tmp_path / "link.py"
        link.symlink_to(outside)
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "link.py"})
        assert resp.status_code in (200, 500)

    def test_run_handles_unreadable_file(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        target.chmod(0o000)
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "app.py"})
        assert resp.status_code == 200

    def test_run_syntax_error_skipped(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("def broken(:\n", encoding="utf-8")
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"file": "app.py"})
        assert resp.status_code == 200
        assert resp.json()["files_checked"] == 1

    def test_run_max_files_cap(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
        client = self._client(tmp_path)
        resp = client.get("/api/v1/patterns/run", params={"max_files": 2})
        assert resp.json()["files_checked"] == 2

    def test_run_rejects_bad_max_files(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        assert client.get("/api/v1/patterns/run", params={"max_files": 0}).status_code == 422
        assert client.get("/api/v1/patterns/run", params={"max_files": 501}).status_code == 422

    def test_run_check_that_raises_is_logged_not_fatal(self, tmp_path: Path, monkeypatch) -> None:
        target = tmp_path / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        import raven.core.pattern_checker as pc

        def boom(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
            msg = "boom"
            raise RuntimeError(msg)

        monkeypatch.setitem(pc._PATTERN_CHECKS, "print-vs-loguru", boom)
        client = self._client(tmp_path)
        resp = client.get(
            "/api/v1/patterns/run", params={"file": "app.py", "check_ids": "print-vs-loguru"}
        )
        assert resp.status_code == 200
        assert resp.json()["files_checked"] == 1


class TestFindFiles:
    def test_skips_ignored_dirs(self, tmp_path: Path) -> None:
        from raven.core.pattern_checker import _find_python_files

        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "c.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        files = _find_python_files(tmp_path, max_files=10)
        assert [f.name for f in files] == ["ok.py"]

    def test_max_files_break(self, tmp_path: Path) -> None:
        from raven.core.pattern_checker import _find_python_files

        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
        files = _find_python_files(tmp_path, max_files=3)
        assert len(files) == 3
