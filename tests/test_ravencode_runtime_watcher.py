from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import ravencode.runtime.watcher as watcher_mod
from ravencode.runtime.watcher import FileWatcher, get_watcher, watch_files


@pytest.fixture(autouse=True)
def reset_watcher() -> Generator[None, None, None]:
    watcher_mod._watcher = None
    yield
    watcher_mod._watcher = None


def _single_pass_sleeper(watcher: FileWatcher) -> Callable[[float], Awaitable[None]]:
    async def sleeper(_: float) -> None:
        watcher._running = False

    return sleeper


class TestFileWatcher:
    def test_resolves_paths(self, tmp_path) -> None:
        watcher = FileWatcher([str(tmp_path / "a.txt")])
        assert str(watcher._paths[0]) == str((tmp_path / "a.txt").resolve())

    def test_on_change_sets_handler(self) -> None:
        watcher = FileWatcher([])
        handler = AsyncMock()
        watcher.on_change(handler)
        assert watcher._on_change is handler

    async def test_start_and_stop(self, monkeypatch) -> None:
        watcher = FileWatcher(["nope.txt"], interval=0.01)
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher.start()
        assert watcher._running is True
        assert watcher._task is not None
        task = watcher._task
        await task
        await watcher.stop()
        assert watcher._running is False
        assert watcher._task is None

    async def test_poll_detects_change(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "a.txt"
        f.write_text("old")
        watcher = FileWatcher([str(f)])
        watcher._running = True
        watcher._snapshots[str(f.resolve())] = 0.0
        calls: list[str] = []

        async def record(key: str) -> None:
            calls.append(key)

        watcher.on_change(record)
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher._poll()
        assert calls == [str(f.resolve())]
        assert watcher._snapshots[str(f.resolve())] == f.stat().st_mtime

    async def test_poll_records_new_file(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "b.txt"
        f.write_text("x")
        watcher = FileWatcher([str(f)])
        watcher._running = True
        calls: list[str] = []

        async def record(key: str) -> None:
            calls.append(key)

        watcher.on_change(record)
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher._poll()
        assert calls == []
        assert watcher._snapshots[str(f.resolve())] == f.stat().st_mtime

    async def test_poll_skips_missing_file(self, monkeypatch) -> None:
        watcher = FileWatcher(["missing.txt"])
        watcher._running = True
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher._poll()
        assert watcher._snapshots == {}

    async def test_poll_handler_exception(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "c.txt"
        f.write_text("x")
        watcher = FileWatcher([str(f)])
        watcher._running = True
        watcher._snapshots[str(f.resolve())] = 0.0

        async def bad_handler(key: str) -> None:
            raise RuntimeError("boom")

        watcher.on_change(bad_handler)
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher._poll()
        assert watcher._snapshots[str(f.resolve())] == f.stat().st_mtime

    async def test_poll_no_change_no_handler(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "d.txt"
        f.write_text("x")
        watcher = FileWatcher([str(f)])
        watcher._running = True
        mtime = f.stat().st_mtime
        watcher._snapshots[str(f.resolve())] = mtime
        calls: list[str] = []
        watcher.on_change(calls.append)  # type: ignore[arg-type]
        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", _single_pass_sleeper(watcher))
        await watcher._poll()
        assert calls == []


class TestWatcherGlobals:
    def test_get_watcher_singleton(self) -> None:
        assert get_watcher() is get_watcher()

    def test_get_watcher_default_paths(self) -> None:
        assert get_watcher()._paths == [Path().expanduser().resolve()]

    async def test_watch_files(self, tmp_path, monkeypatch) -> None:
        target = tmp_path / "e.txt"
        target.write_text("x")

        async def sleeper(_: float) -> None:
            w = watcher_mod._watcher
            if w is not None:
                w._running = False

        monkeypatch.setattr("ravencode.runtime.watcher.asyncio.sleep", sleeper)
        result = await watch_files([str(target)])
        assert result == "[ok] watching 1 file(s)"
        watcher = watcher_mod._watcher
        assert watcher is not None
        assert watcher._running is True
        await asyncio.sleep(0)
        await watcher.stop()
        assert watcher._running is False
