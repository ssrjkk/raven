"""Hot reload of a user plugin, end to end: real worker, real edited file, no mocks.

The unit suite (`tests/test_ravencode_runtime_plugins.py`) patches `_load_untrusted_plugin`, which
cannot prove the part that matters: that editing a plugin file while the gateway runs swaps the
interpreter that answers the tool, that the namespaced tool name survives the swap, and that the
replaced worker is actually reaped rather than left running. Measured before this wave none of it
could happen at all — `watch()` was started by nothing, `stop_watch()` and `stop_untrusted_plugins()`
had zero callers, and a reload notification hook (`set_on_reload`) had no subscriber, so tool-surface
invalidation had to move to the mutation site.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import ravencode.runtime.plugins as plugins_mod
import ravencode.runtime.tools.registry as registry_mod
from raven.core.plugin_loader import _WORKER_POOL
from ravencode.runtime.plugins import (
    discover_plugins,
    register_all_plugins,
    shutdown_plugins,
)
from ravencode.runtime.tools.definitions import MODULE_TOOLS

API_IMPORT = "from ravencode.runtime.plugins import Plugin\n\n"


def _source(greeting: str, description: str) -> str:
    return (
        API_IMPORT
        + f"""
def register(ctx=None):
    async def hello(name: str) -> str:
        return "{greeting} " + name
    return Plugin(name="greeter", tools={{"hello": {{"name": "hello", "description": "{description}",
        "parameters": {{"type": "object", "properties": {{"name": {{"type": "string"}}}}}},
        "handler": hello}}}})
"""
    )


@pytest.fixture
def plugin_file(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "greeter"
    plugin_dir.mkdir()
    f = plugin_dir / "plugin.py"
    f.write_text(_source("hi", "Greet once."), encoding="utf-8")
    return f


@pytest.fixture(autouse=True)
async def _clean_and_reap() -> AsyncIterator[None]:
    def reset() -> None:
        plugins_mod._plugin_registry = None
        plugins_mod._plugins_attempted = False
        plugins_mod._plugins_loop = None
        registry_mod.invalidate_plugin_tools()

    reset()
    yield
    await shutdown_plugins()
    reset()


def _touch_newer(f: Path) -> None:
    """NTFS can hand back an identical mtime for two writes in the same millisecond; make it newer."""
    stat = f.stat()
    os.utime(f, (stat.st_atime, stat.st_mtime + 2.0))


async def _registered(plugin_file: Path) -> Any:
    assert await register_all_plugins(plugin_file.parent.parent) == 1
    return plugins_mod.get_plugin_registry()


class TestReloadPicksUpAnEditedPlugin:
    async def test_the_edited_tool_answers_differently_after_a_reload(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        tool_name = "greeter.hello"
        assert await reg.get_plugin("greeter").tools[tool_name]["handler"](name="bob") == "hi bob"

        plugin_file.write_text(_source("yo", "Greet twice."), encoding="utf-8")
        _touch_newer(plugin_file)
        await reg._check_reload()

        assert await reg.get_plugin("greeter").tools[tool_name]["handler"](name="bob") == "yo bob"

    async def test_the_tool_surface_and_its_metadata_follow_the_reload(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)

        def surface() -> dict[str, str]:
            return {
                d["function"]["name"]: d["function"]["description"]
                for d in registry_mod.get_tool_definitions()
                if d["function"]["name"].startswith("greeter.")
            }

        assert surface() == {"greeter.hello": "Greet once."}
        plugin_file.write_text(_source("yo", "Greet twice."), encoding="utf-8")
        _touch_newer(plugin_file)
        await reg._check_reload()
        assert surface() == {"greeter.hello": "Greet twice."}

    async def test_the_replaced_worker_is_reaped_not_orphaned(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        key = str(plugin_file)
        first = _WORKER_POOL[key]._process
        assert first is not None and first.returncode is None

        plugin_file.write_text(_source("yo", "Greet twice."), encoding="utf-8")
        _touch_newer(plugin_file)
        await reg._check_reload()

        second = _WORKER_POOL[key]._process
        assert second is not None
        assert second.pid != first.pid
        # the child the reload replaced is gone: this is the leak `shutdown_plugins()` cannot cover
        assert first.returncode is not None

    async def test_an_unrelated_change_is_not_a_reload(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        recorded = dict(reg._file_mtimes)
        await reg._check_reload()
        assert reg._file_mtimes == recorded
        assert reg.get_plugin("greeter") is not None

    async def test_a_file_that_stops_parsing_drops_the_plugin(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        names = {d["function"]["name"] for d in registry_mod.get_tool_definitions()}
        assert "greeter.hello" in names

        plugin_file.write_text("def :\n", encoding="utf-8")
        _touch_newer(plugin_file)
        await reg._check_reload()
        assert reg.get_plugin("greeter") is None
        assert "greeter.hello" not in MODULE_TOOLS
        assert "greeter.hello" not in {d["function"]["name"] for d in registry_mod.get_tool_definitions()}


class TestWatcherDrivenReload:
    async def test_the_watcher_applies_the_edit_on_its_own(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        await reg.watch(interval=0.05)
        try:
            plugin_file.write_text(_source("ho", "Greet thrice."), encoding="utf-8")
            _touch_newer(plugin_file)
            description = ""
            for _ in range(60):
                await asyncio.sleep(0.05)
                plugin = reg.get_plugin("greeter")
                description = plugin.tools["greeter.hello"]["description"] if plugin else ""
                if description == "Greet thrice.":
                    break
            assert description == "Greet thrice."
        finally:
            await reg.stop_watch()

    async def test_the_reload_keeps_one_worker_per_plugin_file(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        for greeting in ("a", "b", "c"):
            plugin_file.write_text(_source(greeting, "d"), encoding="utf-8")
            _touch_newer(plugin_file)
            await reg._check_reload()
        assert len(_WORKER_POOL) == 1
        alive = [w for w in _WORKER_POOL.values() if w._process and w._process.returncode is None]
        assert len(alive) == 1

    async def test_shutdown_reaps_every_worker_and_the_watcher(self, plugin_file: Path) -> None:
        reg = await _registered(plugin_file)
        await reg.watch(interval=30.0)
        assert reg._watch_task is not None
        await shutdown_plugins()
        assert reg._watch_task is None
        assert _WORKER_POOL == {}


class TestDiscoveryOfTheRealTree:
    async def test_discovering_the_shipped_example_plugin(self, tmp_path: Path) -> None:
        """`plugins/example-http` is what the guide tells an operator to copy; it has to load."""
        src = Path(__file__).resolve().parents[2] / "plugins" / "example-http"
        if not (src / "plugin.py").exists():
            pytest.skip("the example plugin is not in this checkout")
        target = tmp_path / "example-http"
        target.mkdir()
        (target / "plugin.py").write_text((src / "plugin.py").read_text(encoding="utf-8"), encoding="utf-8")
        found = await discover_plugins(tmp_path)
        assert [p.name for p in found] == ["example-http"]
        names = sorted(found[0].tools)
        assert names == ["example-http.http_get", "example-http.http_post"]
        assert found[0].tools["example-http.http_post"]["dangerous"] is True


def _child_running(pid: int) -> bool:
    """Whether a pid is still executing; an exited child nobody reaped does not count as running."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, IndexError):
        return True


async def _wait_until_dead(pid: int, attempts: int = 40) -> bool:
    for _ in range(attempts):
        if not _child_running(pid):
            return True
        await asyncio.sleep(0.05)
    return False


def _lose_the_pid(monkeypatch: pytest.MonkeyPatch, worker: Any) -> None:
    """Make one worker's kill behave the way uvloop's does once the OS has lost the child.

    The state is the real one: a loop that closed reaped its subprocess without setting `returncode`,
    so `stop()` cannot see the death and the pid check fails with `ProcessLookupError`. The child is
    terminated for real first, so the assertion about the dead pid means something on a runner that
    cannot install uvloop; only the reporting of the lost pid is substituted.
    """
    proc = worker._process
    assert proc is not None, "the loop that came and went must leave its worker in the pool"
    terminate = proc.kill

    def kill() -> None:
        terminate()
        raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(proc, "kill", kill)


def _on_a_dying_loop(plugin_file: Path) -> tuple[int, Any]:
    """Register a plugin on its own event loop in a thread, and let that loop close.

    This is the shape the process-global state cannot survive on its own: a surface that came and went
    (`asyncio.run`, a TUI session, the next request cycle) leaves its worker in the pool with an owner
    loop that no longer runs. Doing it in a thread is what lets the test then act on a second live loop.
    """

    def run() -> tuple[int, Any]:
        async def body() -> tuple[int, Any]:
            assert await register_all_plugins(plugin_file.parent.parent) == 1
            worker = _WORKER_POOL[str(plugin_file)]
            assert worker._process is not None
            return worker._process.pid, worker

        return asyncio.run(body())

    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = run()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=30.0)
    assert not thread.is_alive(), "the first loop never finished"
    if "error" in result:
        raise result["error"]
    value: tuple[int, Any] = result["value"]
    return value


class TestAWorkerFromAClosedLoop:
    """The pool is process-global; the pipes are not. Both facts have to survive each other.

    Measured, 8 tests failing in the full suite: a surface that started its worker on an
    `asyncio.run` that had since ended still held the pool entry and the registry entry, so the next
    surface offered a tool nobody could answer, and its own shutdown awaited a future attached to the
    closed loop — `RuntimeError: got Future attached to a different loop`, out of the exit path, with
    the child left running.
    """

    async def test_shutting_down_a_worker_another_loop_started_does_not_raise(self, plugin_file: Path) -> None:
        pid, orphan = _on_a_dying_loop(plugin_file)
        assert len(_WORKER_POOL) == 1
        await shutdown_plugins()
        assert _WORKER_POOL == {}
        assert await _wait_until_dead(pid), f"worker pid {pid} outlived the shutdown"
        with pytest.raises(RuntimeError, match="another event loop"):
            await orphan.send_command({"type": "ping"})

    async def test_the_next_loop_gets_a_worker_it_can_actually_call(self, plugin_file: Path) -> None:
        _on_a_dying_loop(plugin_file)
        stale = plugins_mod.get_plugin_registry().get_plugin("greeter")
        assert stale is not None
        assert await register_all_plugins(plugin_file.parent.parent) == 1
        fresh = plugins_mod.get_plugin_registry().get_plugin("greeter")
        assert fresh is not None and fresh is not stale
        answer = await asyncio.wait_for(fresh.tools["greeter.hello"]["handler"](name="bob"), timeout=10.0)
        assert answer == "hi bob"

    async def test_a_worker_this_loop_started_is_not_spawned_twice(self, plugin_file: Path) -> None:
        assert await register_all_plugins(plugin_file.parent.parent) == 1
        first = _WORKER_POOL[str(plugin_file)]
        assert await register_all_plugins(plugin_file.parent.parent) == 1
        assert _WORKER_POOL[str(plugin_file)] is first

    async def test_a_child_the_os_already_lost_is_stopped_not_an_error(
        self, plugin_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The child can be gone before `returncode` ever learns it, and that is not a failure.

        Measured in CI, where uvloop is installed and probes the pid before signalling: `stop()` took
        `ProcessLookupError` out of the shutdown path, so every surface that shut plugins down on exit
        reported a broken test instead of a stopped worker, and the pool entry survived. uvloop cannot
        be installed on Windows, so the pid probe is the only part substituted here.
        """
        pid, orphan = _on_a_dying_loop(plugin_file)
        _lose_the_pid(monkeypatch, orphan)
        await shutdown_plugins()
        assert _WORKER_POOL == {}
        assert await _wait_until_dead(pid), f"worker pid {pid} outlived the shutdown"

    async def test_a_lost_worker_does_not_poison_the_next_registration(
        self, plugin_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registration stops the pooled worker before adopting its replacement — measured 0 plugins.

        The exception escaped `register_untrusted_plugin`'s handler, which then reported a plugin that
        loads fine as undiscoverable, so the tool surface shipped without it.
        """
        _on_a_dying_loop(plugin_file)
        _lose_the_pid(monkeypatch, _WORKER_POOL[str(plugin_file)])
        assert await register_all_plugins(plugin_file.parent.parent) == 1
        fresh = plugins_mod.get_plugin_registry().get_plugin("greeter")
        assert fresh is not None
        answer = await asyncio.wait_for(fresh.tools["greeter.hello"]["handler"](name="bob"), timeout=10.0)
        assert answer == "hi bob"
