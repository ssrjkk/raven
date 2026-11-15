from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from raven.core.config_watcher import ConfigWatcher
from tests.core.switch_fixtures import switch_env, switch_names

# pytest asks for a fixture by name and never reads the import, so ruff would call both bindings unused
# and every `switch_env` parameter a redefinition of one. `test_the_switch_fixtures_are_imported_not_inherited`
# in test_runtime_switches.py requires a module that requests either name to import both.
_FIXTURES = (switch_env, switch_names)

_TEST_KEYS = ["RAVEN_CW_FOO", "RAVEN_CW_BAR"]


def _cleanup_env() -> None:
    for k in _TEST_KEYS:
        os.environ.pop(k, None)


def test_reload_env_sets_valid_skips_invalid_and_blocked(tmp_path: Path) -> None:
    _cleanup_env()
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "RAVEN_CW_FOO=bar",
                "lowercase=nope",
                "9START=nope",
                "NOEQUALSIGN",
                "PATH=/should/be/ignored",
                "RAVEN_CW_BAR=   spaced   ",
            ]
        )
    )
    w = ConfigWatcher(str(env))
    try:
        w._reload_env()
        assert os.environ.get("RAVEN_CW_FOO") == "bar"
        assert os.environ.get("RAVEN_CW_BAR") == "spaced"  # stripped
        assert "lowercase" not in os.environ
        assert "9START" not in os.environ
        assert os.environ.get("PATH") != "/should/be/ignored"  # blocked key never applied
    finally:
        _cleanup_env()


def test_reload_env_missing_file_returns(tmp_path: Path) -> None:
    w = ConfigWatcher(str(tmp_path / "absent.env"))
    w._reload_env()  # must not raise


def test_a_quoted_value_reloads_as_the_value_settings_reads(tmp_path: Path) -> None:
    """The watcher pushes the file into ``os.environ`` and ``Settings`` reads the same file through
    python-dotenv, which hands a quoted value over unquoted. The watcher's own inline parser kept the
    quotes, so an operator who wrote ``TELEGRAM_BOT_TOKEN="123:abc"`` got a channel rebuilt on a token two
    characters longer than the one the next restart builds.
    """
    _cleanup_env()
    env = tmp_path / ".env"
    env.write_text("RAVEN_CW_FOO=\"bar\"\nRAVEN_CW_BAR='baz'\n")
    w = ConfigWatcher(str(env))
    try:
        w._reload_env()
        assert os.environ["RAVEN_CW_FOO"] == "bar"
        assert os.environ["RAVEN_CW_BAR"] == "baz"
    finally:
        _cleanup_env()


def test_the_watcher_has_no_second_copy_of_the_format() -> None:
    """One parser, because two is what let a switch mean one thing at boot and another after an edit."""
    import inspect

    from raven.core import config_watcher

    assert "parse_env_file" in inspect.getsource(config_watcher.ConfigWatcher._reload_env)
    assert "_BLOCKED_KEYS" not in vars(config_watcher)
    assert not hasattr(config_watcher, "_ENV_KEY_PATTERN")


@pytest.mark.asyncio
async def test_get_mtime_matches_stat(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("RAVEN_CW_FOO=x\n")
    w = ConfigWatcher(str(env))
    try:
        assert w._get_mtime() == env.stat().st_mtime
    finally:
        _cleanup_env()


@pytest.mark.asyncio
async def test_start_when_file_missing_then_stop() -> None:
    w = ConfigWatcher("does-not-exist.env", check_interval=0.01)
    await w.start()
    assert w._running
    assert w._last_mtime == 0.0
    assert w._task is not None
    await w.stop()
    assert not w._running
    assert w._task.done()


@pytest.mark.asyncio
async def test_watch_loop_reloads_and_fires_listeners(tmp_path: Path) -> None:
    _cleanup_env()
    env = tmp_path / ".env"
    env.write_text("RAVEN_CW_FOO=one\n")
    w = ConfigWatcher(str(env), check_interval=0.01)

    fired: list[str] = []
    boom: list[str] = []

    def ok_listener() -> None:
        fired.append("ok")

    def bad_listener() -> None:
        boom.append("x")
        raise ValueError("listener exploded")

    w._listeners = [ok_listener, bad_listener]
    await w.start()
    try:
        # advance mtime beyond the recorded baseline to trigger a reload
        env.write_text("RAVEN_CW_BAR=two\n")
        future = env.stat().st_mtime + 5
        os.utime(env, (future, future))
        for _ in range(300):
            if fired:
                break
            await asyncio.sleep(0.01)
        assert fired, "listener was never called"
        assert boom, "erroring listener should still run then be caught"
        assert os.environ.get("RAVEN_CW_BAR") == "two"
        assert w._task is not None and not w._task.done()
    finally:
        await w.stop()
        _cleanup_env()


@pytest.mark.asyncio
async def test_watch_loop_survives_stat_error(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("RAVEN_CW_FOO=x\n")
    w = ConfigWatcher(str(env), check_interval=0.01)

    def raise_oserror() -> float:
        raise OSError("stat failed")

    await w.start()
    w._get_mtime = raise_oserror  # type: ignore[method-assign]
    try:
        await asyncio.sleep(0.05)
        assert w._task is not None and not w._task.done()
    finally:
        await w.stop()


def test_with_no_path_it_watches_the_file_settings_actually_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gateway starts a watcher with no argument, so the default must be the obeyed file.

    Before this, a switch written into ``~/.raven/.env`` was watched while the operator's ``./.env``
    decided the value, and the two disagreed in silence.
    """
    from raven.core import config

    target = tmp_path / ".env"
    monkeypatch.setattr(config, "effective_env_file", lambda: target)
    assert ConfigWatcher().env_path == target


@pytest.mark.asyncio
async def test_a_written_switch_reaches_the_live_settings_without_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch_names: None
) -> None:
    """The whole promise of the switch in one test: write the file, the running process follows."""
    from raven.core.config import refresh_settings_from_env, settings

    env = tmp_path / ".env"
    env.write_text("DEFAULT_MODEL=before\n", encoding="utf-8")
    monkeypatch.setattr(settings, "default_model", "before")

    w = ConfigWatcher(str(env), check_interval=0.01)
    w.add_listener(refresh_settings_from_env)
    await w.start()
    try:
        await asyncio.sleep(0.05)
        env.write_text("DEFAULT_MODEL=ollama/hf.co/mradermacher/x:Q4_K_M\n", encoding="utf-8")
        deadline = asyncio.get_event_loop().time() + 5.0
        while settings.default_model == "before" and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        assert os.environ["DEFAULT_MODEL"] == "ollama/hf.co/mradermacher/x:Q4_K_M"
        assert settings.default_model == "ollama/hf.co/mradermacher/x:Q4_K_M", (
            "the env reached the process but not the settings the router reads"
        )
    finally:
        await w.stop()
        _cleanup_env()
