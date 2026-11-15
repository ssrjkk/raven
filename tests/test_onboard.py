from __future__ import annotations

import ast
import contextlib
import importlib
import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from raven.cli.onboard import _persist, _prompt_channels, _prompt_llm, _prompt_port, _prompt_security

_CREDENTIAL_NAMES = ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "WEB_SECRET_KEY")


@contextlib.contextmanager
def _file_only(*names: str) -> Iterator[None]:
    """Hold the environment the way a process that was only given the env files holds it.

    ``write_env_value`` exports what it writes, so a reader still inside the test would answer from this
    process's copy and prove nothing about the file. The names go back on the way out of the ``with``, in
    the test rather than in a fixture teardown: a teardown that restores a switch name after
    ``pin_env_names`` has handed control back reads as a leak, and the guard blames the wrong file.
    """
    taken = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in taken.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def wizard_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pin_env_names: Callable[[Iterable[str]], None],
) -> Path:
    """The env-file cascade aimed at one temp file, with everything the wizard writes put back.

    The whole cascade, not only ``effective_env_file()``: an answer is proven by reading it back the way a
    start does, and a reader of the cascade that still reached ``D:\\raven\\.env`` would hand the operator's
    real credentials to the assertion. The names are taken out of the process because ``write_env_value``
    exports as it writes, so an answer would otherwise outlive the test that gave it.
    """
    from raven.core import config as config_module
    from raven.core import config_discovery
    from raven.core.config import runtime_switches

    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(path)])
    pin_env_names(switch.env_name for switch in runtime_switches())
    pin_env_names(_CREDENTIAL_NAMES)
    for switch in runtime_switches():
        monkeypatch.setattr(config_module.settings, switch.attr, getattr(config_module.settings, switch.attr))
    # A credential write forces the discovery scan again and the scan is kept for the process.
    monkeypatch.setattr(config_discovery, "_discovery_cache", config_discovery._discovery_cache)
    return path


def _written(rows: list[tuple[str, str, bool]]) -> list[str]:
    return [name for name, _note, saved in rows if name and saved]


def _refused(rows: list[tuple[str, str, bool]]) -> dict[str, str]:
    return {name: note for name, note, saved in rows if name and not saved}


class TestPromptLlm:
    def test_openrouter_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["openrouter", "sk-test-key", ""])
            result = _prompt_llm(config)
            assert result.get("openrouter_api_key") == "sk-test-key"
            assert "default_model" in result

    def test_anthropic_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["anthropic", "sk-ant-key", ""])
            result = _prompt_llm(config)
            assert result.get("anthropic_api_key") == "sk-ant-key"
            assert "default_model" in result

    def test_openai_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["openai", "sk-openai-key", ""])
            result = _prompt_llm(config)
            assert result.get("openai_api_key") == "sk-openai-key"
            assert "default_model" in result

    def test_ollama_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["ollama", "http://localhost:11434", ""])
            result = _prompt_llm(config)
            assert result.get("ollama_base_url") == "http://localhost:11434"
            assert "default_model" in result


class TestPromptChannels:
    def test_no_channels(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_channels(config)
            assert "discord_bot_token" not in result
            assert "slack_bot_token" not in result

    def test_discord_channel(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Confirm") as MockConfirm, patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockConfirm.ask = MagicMock(side_effect=[True, False])
            MockPrompt.ask = MagicMock(return_value="discord-token-123")
            result = _prompt_channels(config)
            assert result.get("discord_bot_token") == "discord-token-123"


class TestPromptSecurity:
    def test_default_pairing_policy(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt, patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockPrompt.ask = MagicMock(return_value="pairing")
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_security(config)
            assert result.get("dm_policy") == "pairing"

    def test_open_policy(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt, patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockPrompt.ask = MagicMock(return_value="open")
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_security(config)
            assert result.get("dm_policy") == "open"


class TestPromptPort:
    def test_default_port(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(return_value="")
            result = _prompt_port(config)
            assert result.get("web_port") == ""

    def test_custom_port_stays_as_typed(self):
        """The wizard does not coerce: an answer that is not a port has to survive to the switch that
        refuses it, or the refusal — and the reason in it — never happens."""
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(return_value="8080")
            result = _prompt_port(config)
            assert result.get("web_port") == "8080"


class TestAnswersReachAStart:
    """Every answer has to land where a start reads it, and an answer that cannot must say so.

    The wizard used to end with ``config_store.save()``, which wrote ``~/.raven/config.json`` — a file
    measured on 2026-11-14 to have no reader in the tree — and ``apply_to_env()``, which exported into the
    wizard's own process. Measured in a fresh process afterwards: ``DEFAULT_MODEL`` stayed at the install
    default, ``DM_POLICY`` stayed ``pairing``, ``WEB_PORT`` stayed ``18888`` and the written API key was
    still absent from ``Settings``, while ``raven onboard`` had printed ``Setup complete!``. These tests
    read the file back the way a start does, so the destination is the assertion rather than the promise.
    """

    async def test_a_switch_answer_is_read_by_the_next_settings_build(self, wizard_env: Path):
        from raven.core.config import Settings

        rows = await _persist({"default_model": "openrouter/test/model"})
        assert _written(rows) == ["DEFAULT_MODEL"]
        assert "DEFAULT_MODEL=openrouter/test/model" in wizard_env.read_text(encoding="utf-8")
        with _file_only("DEFAULT_MODEL"):
            fresh = Settings(_env_file=wizard_env)  # type: ignore[call-arg]
            assert fresh.default_model == "openrouter/test/model"

    async def test_a_credential_answer_reaches_the_provider_that_uses_it(self, wizard_env: Path):
        from raven.core.config import Settings

        rows = await _persist({"openrouter_api_key": "sk-or-v1-testtesttesttest"})
        assert _written(rows) == ["OPENROUTER_API_KEY"]
        with _file_only("OPENROUTER_API_KEY"):
            fresh = Settings(_env_file=wizard_env)  # type: ignore[call-arg]
            assert fresh.openrouter_api_key.get_secret_value() == "sk-or-v1-testtesttesttest"

    async def test_a_policy_answer_moves_the_field_the_gateway_asks(self, wizard_env: Path):
        from raven.core.config import Settings

        rows = await _persist({"dm_policy": "open"})
        assert _written(rows) == ["DM_POLICY"]
        with _file_only("DM_POLICY"):
            fresh = Settings(_env_file=wizard_env)  # type: ignore[call-arg]
            assert fresh.dm_policy == "open"

    async def test_a_channel_token_reaches_the_channel_after_adoption(self, wizard_env: Path):
        """A channel credential is the one answer a file cannot deliver on its own.

        Channels build their token from ``os.environ`` in ``__init__``, and there is no ``load_dotenv`` in
        this tree, so a token that is only in the file — the state a wizard write leaves behind — stays
        invisible until a process adopts the files. Measured: with ``TELEGRAM_BOT_TOKEN`` in the file its own
        ``Settings`` had read, ``configured_channels()`` answered ``[]``.
        """
        from raven.core.channel_config import configured_channels, get_channel_config
        from raven.core.config import apply_env_files_to_environ

        rows = await _persist({"telegram_bot_token": "123456:SENTINEL-FOR-WIZARD"})
        assert _written(rows) == ["TELEGRAM_BOT_TOKEN"]
        assert "TELEGRAM_BOT_TOKEN=123456:SENTINEL-FOR-WIZARD" in wizard_env.read_text(encoding="utf-8")

        with _file_only("TELEGRAM_BOT_TOKEN"):
            assert get_channel_config("telegram") == {}
            assert "telegram" not in configured_channels()
            assert "TELEGRAM_BOT_TOKEN" in apply_env_files_to_environ()
            assert get_channel_config("telegram") == {"bot_token": "123456:SENTINEL-FOR-WIZARD"}
            assert "telegram" in configured_channels()

    async def test_an_answer_no_code_reads_is_refused_instead_of_reported_saved(self, wizard_env: Path):
        rows = await _persist({"telegram_token": "123456:SENTINEL"})
        assert _written(rows) == []
        assert "no code reads" in _refused(rows)["TELEGRAM_TOKEN"]
        assert "TELEGRAM_TOKEN" not in wizard_env.read_text(encoding="utf-8")

    async def test_an_empty_answer_is_left_alone(self, wizard_env: Path):
        rows = await _persist({"default_model": "   "})
        assert _written(rows) == []
        assert wizard_env.read_text(encoding="utf-8") == ""

    async def test_an_answer_the_switch_cannot_hold_is_refused_with_its_reason(self, wizard_env: Path):
        rows = await _persist({"web_port": "not-a-port"})
        assert _written(rows) == []
        assert "must be an integer" in _refused(rows)["WEB_PORT"]
        assert "WEB_PORT" not in wizard_env.read_text(encoding="utf-8")

    async def test_an_answer_that_needs_a_restart_says_so(self, wizard_env: Path):
        rows = await _persist({"web_port": "19999"})
        assert _written(rows) == ["WEB_PORT"]
        assert any("restart" in note for _name, note, _saved in rows)

    async def test_an_export_that_outranks_the_file_is_named(self, wizard_env: Path, monkeypatch):
        monkeypatch.setenv("WEB_SECRET_KEY", "value-from-the-shell")
        rows = await _persist({"web_secret_key": "value-from-the-wizard"})
        assert _written(rows) == ["WEB_SECRET_KEY"]
        assert any("export wins" in note for _name, note, _saved in rows)


class TestOnboardStillUsesOneStore:
    """The wizard must not grow a second place an answer goes.

    ``raven/core/config_store.py`` was that second place: the wizard wrote a JSON copy of every answer into
    ``~/.raven/config.json``, nothing read the file, and ``save()`` created it world-readable (mode 0o666,
    measured 2026-11-14) while holding API keys. A re-added store is the shape of bug that leaves every
    test above passing, because they assert on the destination the wizard writes to *now*.
    """

    def test_the_store_is_gone_and_the_wizard_does_not_import_it(self) -> None:
        import raven.cli.onboard as onboard_module

        source = Path(onboard_module.__file__).read_text(encoding="utf-8")
        assert "core.config_store" not in source
        assert "import config_store" not in source
        assert not (Path(onboard_module.__file__).parent.parent / "core" / "config_store.py").exists()
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("raven.core.config_store")


def _answered_keys() -> set[str]:
    """Every name the wizard's prompts can put into the answer dict."""
    import raven.cli.onboard as onboard_module

    tree = ast.parse(Path(onboard_module.__file__).read_text(encoding="utf-8"))
    return {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }


class TestEveryAnswerIsReadable:
    """The wizard's own key list is the surface an operator can configure, so the surface is walked here.

    ``config_store.apply_to_env()`` exported seventeen names, among them ``PAIRING_CODE_LENGTH``, which no
    code in the tree reads: the wizard kept asking because the store kept the answer, and the operator kept
    setting a knob with no effect. A prompt is only allowed to ask for a name something acts on.
    """

    def test_every_prompt_asks_for_a_name_something_reads(self) -> None:
        from raven.core.channel_config import channel_reading
        from raven.core.config import Settings, runtime_switch_keys

        answered = _answered_keys()
        assert answered, "the scan found no prompts — it is vacuous"
        switches = set(runtime_switch_keys())
        unread = sorted(
            key
            for key in answered
            if key not in switches and channel_reading(key.upper()) is None and key not in Settings.model_fields
        )
        assert unread == [], f"the wizard collects answers nothing reads: {unread}"

    def test_the_wizard_still_asks_for_the_it_needs_to_run(self) -> None:
        """A gate that only refuses can be satisfied by deleting the prompts, which is not the fix."""
        assert _answered_keys() == {
            "anthropic_api_key",
            "default_model",
            "discord_bot_token",
            "dm_policy",
            "ollama_base_url",
            "openai_api_key",
            "openrouter_api_key",
            "slack_bot_token",
            "telegram_bot_token",
            "web_port",
            "web_secret_key",
        }
