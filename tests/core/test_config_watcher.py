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
