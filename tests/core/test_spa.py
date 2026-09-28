from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.spa import _candidate_dirs, mount_spa, resolve_web_dist


class TestMountSpa:
    def test_returns_false_when_dist_not_exists(self, tmp_path: Path):
        app = FastAPI()
        missing_dir = tmp_path / "nonexistent"
        result = mount_spa(app, missing_dir)
        assert result is False

    def test_returns_true_when_dist_exists(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        result = mount_spa(app, web_dist)
        assert result is True

    def test_mounts_assets_when_present(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        assets = web_dist / "assets"
        assets.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        result = mount_spa(app, web_dist)
        assert result is True

    def test_spa_fallback_returns_index(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html><body>Test</body></html>")

        mount_spa(app, web_dist)
        client = TestClient(app)

        response = client.get("/some/route")
        assert response.status_code == 200
        assert "Test" in response.text

    def test_spa_fallback_rejects_api_paths(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        mount_spa(app, web_dist)
        client = TestClient(app)

        response = client.get("/api/something")
        assert response.status_code == 404

    def test_missing_dist_is_skipped(self):
        app = FastAPI()
        assert mount_spa(app, None) is False


class TestResolveWebDist:
    @pytest.fixture(autouse=True)
    def _clear_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RAVEN_WEB_DIST", raising=False)

    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        dist = tmp_path / "built"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        monkeypatch.setenv("RAVEN_WEB_DIST", str(dist))

        assert resolve_web_dist() == dist

    def test_override_without_index_is_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("RAVEN_WEB_DIST", str(empty))

        assert resolve_web_dist() != empty

    def test_candidates_start_with_override_and_include_web_dist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        override = tmp_path / "custom-dist"
        monkeypatch.setenv("RAVEN_WEB_DIST", str(override))

        candidates = _candidate_dirs()
        assert candidates[0] == override
        assert any(candidate.parts[-2:] == ("web", "dist") for candidate in candidates)

    def test_candidates_include_package_local_staged_dist(self):
        import raven

        package_dist = Path(raven.__file__).resolve().parent / "web" / "dist"
        assert package_dist in _candidate_dirs()
