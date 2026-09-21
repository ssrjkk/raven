from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.dream_api import _get_dream_skills, _get_memory_stats, create_dream_router


class TestGetMemoryStats:
    async def test_empty_manager(self):
        mgr = MagicMock()
        mgr.working = None
        mgr.session = None
        mgr.long_term = None
        mgr.knowledge = None
        stats = await _get_memory_stats(mgr)
        assert stats == {}

    async def test_manager_with_stores(self):
        mgr = MagicMock()
        working_store = AsyncMock()
        working_store.list_keys.return_value = ["key1", "key2"]
        mgr.working = working_store
        mgr.session = None
        mgr.long_term = None
        mgr.knowledge = None

        stats = await _get_memory_stats(mgr)
        assert stats == {"working": 2}

    async def test_manager_with_error(self):
        mgr = MagicMock()
        working_store = AsyncMock()
        working_store.list_keys.side_effect = Exception("Test error")
        mgr.working = working_store
        mgr.session = None
        mgr.long_term = None
        mgr.knowledge = None

        stats = await _get_memory_stats(mgr)
        assert stats == {"working": 0}


class TestGetDreamSkills:
    def test_returns_dream_skills(self):
        with patch("raven.core.skills.list_skills") as mock_list:
            mock_list.return_value = [
                {"name": "skill1", "source": "dream"},
                {"name": "skill2", "source": "builtin"},
                {"name": "skill3", "source": "dream"},
            ]
            skills = _get_dream_skills()
            assert len(skills) == 2
            assert all(s["source"] == "dream" for s in skills)

    def test_returns_empty_when_no_dream_skills(self):
        with patch("raven.core.skills.list_skills") as mock_list:
            mock_list.return_value = [{"name": "skill1", "source": "builtin"}]
            skills = _get_dream_skills()
            assert skills == []


class TestDreamRouter:
    @pytest.fixture
    def client(self, tmp_path: Path):
        app = FastAPI()
        memory_manager = MagicMock()
        dream_engine = MagicMock()
        dream_engine.status.return_value = {"status": "idle"}
        dream_engine.cycle_once = AsyncMock(return_value={"cycles": 1})
        app.state.dream_engine = dream_engine
        app.include_router(create_dream_router(memory_manager))
        return TestClient(app)

    def test_dream_status_endpoint(self, client):
        response = client.get("/api/dream/status")
        assert response.status_code == 200
        assert response.json() == {"status": "idle"}

    async def test_dream_stats_endpoint(self, client, tmp_path: Path):
        with patch("raven.core.dream_api._get_memory_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = {"working": 5}
            with patch("raven.core.dream_api._get_dream_skills") as mock_skills:
                mock_skills.return_value = [{"name": "dream_skill"}]
                response = client.get("/api/dream/stats")
                assert response.status_code == 200
                data = response.json()
                assert "status" in data
                assert data["memory"] == {"working": 5}

    async def test_dream_cycle_endpoint(self, client):
        response = client.post("/api/dream/cycle")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "stats" in data

    async def test_memory_backup_endpoint(self, client, tmp_path: Path):
        with patch("raven.core.backup.export_memory", new_callable=AsyncMock) as mock_export:
            mock_export.return_value = tmp_path / "backup.json"
            response = client.post("/api/memory/backup")
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert "path" in data

    async def test_memory_backups_endpoint(self, client):
        with patch("raven.core.backup.list_backups", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ["backup1.json", "backup2.json"]
            response = client.get("/api/memory/backups")
            assert response.status_code == 200
            data = response.json()
            assert "backups" in data
            assert len(data["backups"]) == 2
