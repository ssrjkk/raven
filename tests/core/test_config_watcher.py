from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from raven.core.config_watcher import ConfigWatcher

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole promise of the switch in one test: write the file, the running process follows."""
    from raven.core.config import refresh_settings_from_env, settings

    env = tmp_path / ".env"
    env.write_text("DEFAULT_MODEL=before\n", encoding="utf-8")
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
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
