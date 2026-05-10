from __future__ import annotations
from pathlib import Path
from raven.core.config import settings


class TestSettings:
    def test_default_model(self):
        assert settings.default_model == "openrouter/anthropic/claude-3-haiku"

    def test_web_port(self):
        assert isinstance(settings.web_port, int)
        assert settings.web_port == 18888

    def test_db_path_resolved(self):
        p = settings.resolved_db_path
        assert isinstance(p, Path)
        assert "raven.db" in str(p)

    def test_vector_db_path(self):
        p = settings.resolved_vector_db_path
        assert isinstance(p, Path)

    def test_data_dir(self):
        d = settings.data_dir
        assert ".raven" in str(d)

    def test_dm_policy_default(self):
        assert settings.dm_policy in ("pairing", "open", "closed")

    def test_parsed_allowed_users_empty(self):
        assert isinstance(settings.parsed_allowed_users, dict)

    def test_log_level(self):
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
