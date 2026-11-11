from __future__ import annotations

import os
import re
import subprocess
import sys
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


class TestSettingsFieldConsumers:
    """Every Settings field must reach something that acts on it.

    ``TestEnvExampleParity`` proves the file and the model agree on which names exist; it cannot
    prove a name does anything, because a field declared in ``raven/core/config.py`` is by
    definition present in the scanned source. ``SANDBOX_BACKEND`` and the seven ``TIER_*`` fields
    passed that guard for months while nothing read them: an operator set them, the admin API saved
    them, ``raven doctor`` reported them, and behaviour never changed.
    """

    _PROD: ClassVar[tuple[str, ...]] = ("raven", "ravencode", "aios", "scripts", "deploy", "policy", ".github")
    _DECLARATIONS: ClassVar[frozenset[str]] = frozenset({"raven/core/config.py", "raven/core/config_store.py"})
    _SUFFIXES: ClassVar[frozenset[str]] = frozenset(
        {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yml", ".yaml", ".toml", ".ps1", ""}
    )

    def _production_source(self) -> tuple[list[Path], str]:
        files = [ROOT / "Dockerfile"]
        for rel in self._PROD:
            files += [
                p
                for p in (ROOT / rel).rglob("*")
                if p.is_file()
                and p.suffix in self._SUFFIXES
                and "__pycache__" not in p.parts
                and p.relative_to(ROOT).as_posix() not in self._DECLARATIONS
            ]
        return files, "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)

    def test_every_settings_field_has_a_consumer(self) -> None:
        files, source = self._production_source()
        assert len(files) > 500, f"consumer scan covered only {len(files)} files — it is vacuous"
        orphans = sorted(
            name
            for name, env_names in _settings_env_candidates().items()
            if not re.search(rf"\b{re.escape(name)}\b", source)
            and not any(re.search(rf"\b{re.escape(env)}\b", source) for env in env_names)
        )
        assert orphans == [], f"Settings fields nothing reads (wire them or delete them): {orphans}"

    def test_no_setting_is_only_writeable(self) -> None:
        """The scan above accepts the env name, which let a field sit unread as long as some code
        read the same variable straight out of os.environ: Settings.jenkins_url and
        Settings.replicate_api_token were exactly that, a second knob for a knob that already
        worked. Here a field counts as consumed only when something reaches it through Settings
        (or config.py itself, which derives resolved_* paths) or maps it in config_store."""
        files, source = self._production_source()
        assert len(files) > 500, f"scan covered only {len(files)} files - it is vacuous"
        assert not re.search(r"settings\.the_setting_nobody_reads", source), "the pattern is matching everything"
        declarations = (ROOT / "raven" / "core" / "config.py").read_text(encoding="utf-8")
        alias_map = (ROOT / "raven" / "core" / "config_store.py").read_text(encoding="utf-8")
        orphans = sorted(
            name
            for name in _settings_env_candidates()
            if f'"{name}"' not in alias_map
            and not re.search(rf"settings\.{name}([^A-Za-z0-9_]|$)", source)
            and not re.search(rf"self\.{name}([^A-Za-z0-9_]|$)", declarations)
        )
        assert orphans == [], f"Settings fields nothing reads through Settings: {orphans}"

    def test_a_field_without_a_consumer_is_caught(self) -> None:
        _, source = self._production_source()
        assert not re.search(r"\bthe_field_nobody_reads\b", source)
        assert not re.search(r"\bTHE_FIELD_NOBODY_READS\b", source)


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


class TestNoProxyEnv:
    """A bracketed IPv6 literal in NO_PROXY used to kill every HTTP client the process builds."""

    def test_brackets_are_dropped_and_duplicates_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import sanitize_no_proxy_env

        monkeypatch.setenv("NO_PROXY", "localhost, .localhost ,127.0.0.1,127.0.0.0/8,[::1],::1,")
        sanitize_no_proxy_env()
        assert os.environ["NO_PROXY"] == "localhost,.localhost,127.0.0.1,127.0.0.0/8,::1"

    def test_an_empty_list_stays_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import sanitize_no_proxy_env

        monkeypatch.setenv("no_proxy", "  ")
        sanitize_no_proxy_env()
        assert os.environ["no_proxy"] == ""

    async def test_a_client_constructs_after_the_rewrite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        from raven.core.config import sanitize_no_proxy_env

        monkeypatch.setenv("NO_PROXY", "localhost,[::1],::1")
        sanitize_no_proxy_env()
        with httpx.Client():
            pass
        async with httpx.AsyncClient():
            pass

    def test_importing_the_config_layer_rewrites_the_environment_of_a_real_process(self, tmp_path: Path) -> None:
        env = dict(os.environ, NO_PROXY="localhost,.localhost,127.0.0.1,[::1],::1")
        code = "import os; import raven.core.config; import httpx; httpx.Client(); print(os.environ['NO_PROXY'])"
        run = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=120
        )
        assert run.returncode == 0, run.stderr
        assert "[::1]" not in run.stdout
        assert "::1" in run.stdout


class TestGhostMode:
    """`raven setup --free` ends by telling the operator to run `raven start --ghost`, so ghost mode
    may not throw away the model that command just downloaded and configured."""

    @pytest.fixture(autouse=True)
    def _restore(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ghost_mode", settings.ghost_mode)
        monkeypatch.setattr(settings, "default_model", settings.default_model)
        monkeypatch.setattr(settings, "ollama_base_url", "http://127.0.0.1:11434")

    def _serves(self, monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
        from raven.core import heretic_model

        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: names)

    def test_the_bundled_model_survives_the_switch_to_ghost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import apply_ghost_mode
        from raven.core.heretic_model import HERETIC_RAVEN_MODEL

        monkeypatch.setattr(settings, "default_model", HERETIC_RAVEN_MODEL)
        self._serves(monkeypatch, [])
        apply_ghost_mode()
        assert settings.ghost_mode is True
        assert settings.default_model == HERETIC_RAVEN_MODEL

    def test_any_ollama_model_the_operator_configured_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import apply_ghost_mode

        monkeypatch.setattr(settings, "default_model", "ollama/qwen2.5:32b")
        self._serves(monkeypatch, [])
        apply_ghost_mode()
        assert settings.default_model == "ollama/qwen2.5:32b"

    def test_a_hosted_name_is_replaced_by_a_model_the_runtime_actually_serves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.config import apply_ghost_mode

        monkeypatch.setattr(settings, "default_model", "groq/openai/gpt-oss-120b")
        self._serves(monkeypatch, ["llama3.1:8b", "qwen2.5:14b"])
        apply_ghost_mode()
        assert settings.default_model == "ollama/llama3.1:8b"

    def test_the_bundled_model_is_preferred_over_whatever_else_is_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.config import apply_ghost_mode
        from raven.core.heretic_model import HERETIC_HF_REF

        monkeypatch.setattr(settings, "default_model", "openrouter/openai/gpt-4o")
        self._serves(monkeypatch, ["llama3", HERETIC_HF_REF])
        apply_ghost_mode()
        assert settings.default_model == f"ollama/{HERETIC_HF_REF}"

    def test_an_unreachable_ollama_is_a_warning_and_a_fallback_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core import heretic_model
        from raven.core.config import apply_ghost_mode

        def _down(*_a: object, **_k: object) -> list[str]:
            raise OSError("connection refused")

        monkeypatch.setattr(heretic_model, "list_ollama_models", _down)
        monkeypatch.setattr(settings, "default_model", "anthropic/claude-sonnet-4-5")
        apply_ghost_mode()
        assert settings.default_model == "ollama/llama3"

    def test_explicit_overrides_still_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import apply_ghost_mode

        monkeypatch.setattr(settings, "default_model", "ollama/qwen2.5:32b")
        self._serves(monkeypatch, [])
        apply_ghost_mode({"default_model": "ollama/custom"})
        assert settings.default_model == "ollama/custom"
