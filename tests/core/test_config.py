from __future__ import annotations

from pathlib import Path
from typing import ClassVar

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


ROOT = Path(__file__).resolve().parents[2]


def _documented_env_names() -> set[str]:
    names = {
        line.split("=", 1)[0].strip().upper()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert names, "no variables parsed from .env.example — both parity guards are vacuous"
    return names


def _settings_env_candidates() -> dict[str, set[str]]:
    """Field name to every environment name pydantic accepts for it."""
    candidates: dict[str, set[str]] = {}
    for field_name, field in Settings.model_fields.items():
        names = {field_name.upper()}
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
        elif alias is not None and hasattr(alias, "choices"):
            names.update(str(choice).upper() for choice in alias.choices)
        candidates[field_name] = names
    return candidates


class TestEnvExampleParity:
    def test_every_setting_is_documented(self) -> None:
        documented = _documented_env_names()
        undocumented = sorted(
            name for name, candidates in _settings_env_candidates().items() if not candidates & documented
        )
        assert undocumented == [], f"settings missing from .env.example: {undocumented}"

    # A name must be readable from code, build files or deployment manifests. Docs and
    # READMEs are excluded on purpose: describing a variable is not consuming it. A library
    # that reads its own env vars (the OTel SDK's OTEL_TRACES_SAMPLER, say) is invisible to
    # this scan, and such a name is still not Raven's to document.
    _CONSUMERS = ("raven", "ravencode", "aios", "scripts", "deploy", "extension", "web/src", ".github")
    _SUFFIXES: ClassVar[frozenset[str]] = frozenset(
        {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yml", ".yaml", ".toml", ".ps1", ""}
    )

    def test_every_documented_env_var_is_consumed(self) -> None:
        """Guard the direction ``test_every_setting_is_documented`` does not cover.

        That test proves ``.env.example`` is complete, so a variable whose feature was
        removed can stay documented forever; this one proves every name in the file is
        still read by something that ships — as a settings field or literally.
        """
        documented = _documented_env_names()
        accepted = {name for names in _settings_env_candidates().values() for name in names}
        haystack = [ROOT / "Dockerfile"]
        for rel in self._CONSUMERS:
            base = ROOT / rel
            haystack += [p for p in base.rglob("*") if p.is_file() and p.suffix in self._SUFFIXES]
        source = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in haystack)

        unread = sorted(n for n in documented if n not in accepted and n not in source)
        assert unread == [], f".env.example documents variables nothing reads: {unread}"


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
