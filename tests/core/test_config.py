from __future__ import annotations

from pathlib import Path

from raven.core.config import settings


class TestSettings:
    def test_default_model(self):
        # default_model is either set in .env or auto-discovered; it must always
        # resolve to a non-empty "<provider>/<model>" string regardless of the
        # ambient configuration.
        assert isinstance(settings.default_model, str)
        assert settings.default_model

    def test_auto_select_model_prefers_groq(self, monkeypatch):
        from raven.core import config_discovery as cd

        result = cd.DiscoveryResult()
        result.providers_available = ["groq"]
        monkeypatch.setattr(cd, "get_discovered_keys", lambda: result)
        assert cd.auto_select_model() == "groq/openai/gpt-oss-120b"

    def test_web_port(self):
        assert isinstance(settings.web_port, int)
        assert settings.web_port == 18888

    def test_db_path_resolved(self):
        p = settings.resolved_db_path
        assert isinstance(p, Path)
        assert "raven.db" in str(p)

    def test_dm_policy_default(self):
        assert settings.dm_policy in ("pairing", "open", "closed")

    def test_log_level(self):
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
