from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.config import Settings, settings


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


class TestEnvExampleParity:
    def test_every_setting_is_documented(self) -> None:
        root = Path(__file__).resolve().parents[2]
        documented = {
            line.split("=", 1)[0].strip().upper()
            for line in (root / ".env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        undocumented: list[str] = []
        for name, field in Settings.model_fields.items():
            candidates = {name.upper()}
            alias = field.validation_alias
            if isinstance(alias, str):
                candidates.add(alias.upper())
            elif alias is not None and hasattr(alias, "choices"):
                candidates.update(str(choice).upper() for choice in alias.choices)
            if not candidates & documented:
                undocumented.append(name)
        assert undocumented == [], f"settings missing from .env.example: {sorted(undocumented)}"


def _settings_without_env_file() -> Settings:
    """Build Settings from the process env only (ignore any developer .env)."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


class TestCriticalModelEnvAliases:
    _NAMES = (
        "CRITICAL_MODEL",
        "CRITICAL_PROVIDER",
        "CRITICAL_API_KEY",
        "RAVEN_CRITICAL_MODEL",
        "RAVEN_CRITICAL_PROVIDER",
        "RAVEN_CRITICAL_API_KEY",
    )

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in self._NAMES:
            monkeypatch.delenv(name, raising=False)

    def test_canonical_env_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CRITICAL_MODEL", "openai/gpt-4o")
        monkeypatch.setenv("CRITICAL_PROVIDER", "openai")
        monkeypatch.setenv("CRITICAL_API_KEY", "sk-test-key")
        loaded = _settings_without_env_file()
        assert loaded.critical_model == "openai/gpt-4o"
        assert loaded.critical_provider == "openai"
        assert loaded.critical_api_key.get_secret_value() == "sk-test-key"

    def test_documented_raven_prefixed_names_still_work(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAVEN_CRITICAL_MODEL", "anthropic/claude-3-5-sonnet")
        monkeypatch.setenv("RAVEN_CRITICAL_PROVIDER", "anthropic")
        monkeypatch.setenv("RAVEN_CRITICAL_API_KEY", "sk-ant-test")
        loaded = _settings_without_env_file()
        assert loaded.critical_model == "anthropic/claude-3-5-sonnet"
        assert loaded.critical_provider == "anthropic"
        assert loaded.critical_api_key.get_secret_value() == "sk-ant-test"

    def test_canonical_name_wins_when_both_are_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CRITICAL_MODEL", "canonical/model")
        monkeypatch.setenv("RAVEN_CRITICAL_MODEL", "legacy/model")
        assert _settings_without_env_file().critical_model == "canonical/model"
