"""User plugins: what actually loads them, and what the sandbox really stops.

Measured on the tree before this wave:

* 0 entry points awaited `register_all_plugins()`. `raven plugins list` reports the *bundled* stack, so
  a plugin dropped in the directory the docs name published nothing anywhere; the tool surface drained a
  registry nothing filled. 7 modules reach it now.
* `discover_plugins`/`register_all_plugins` were sync and owned the loop they ran on. The worker's pipes
  belong to that loop, so even a caller that registered a plugin could not call its tools — the first
  call reached a closed loop.
* `plugins_dir` was written into `raven.json` by `raven init` and `raven setup` and read by nobody, while
  `raven/core/artifacts/paths.py` carried a 6-layer resolver with zero consumers. Two answers for one
  operator setting.
* the sandbox was escapable in three lines: `ravencode.runtime.plugins` was on the import allowlist and
  `Plugin.__init__.__globals__` is the host module's namespace, which holds `Path`. A probe read the live
  64-character `data/web_secret_key` through it without importing anything.
* the worker inherited all 107 parent environment variables — 3 named like credentials
  (CHAINSTACK_API_KEY, TELEGRAM_BOT_TOKEN, WALLETS_KEY) — plus the checkout on `PYTHONPATH`, so an
  escaped child could `import raven.core.config` and read the same secrets from source.

After the fix: the plugin API is a shim whose namespace holds `Plugin` and the restricted builtins only,
and the child starts with 15 environment variables, 0 of them named like credentials, and no importable
`raven*` package.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import textwrap
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

import ravencode.runtime.plugins as plugins_mod
import ravencode.runtime.tools.registry as registry_mod
from ravencode.runtime.plugins import (
    Plugin,
    PluginRegistry,
    discover_plugins,
    ensure_plugin_tools,
    get_plugin_registry,
    plugin_directories,
    plugin_files,
    register_all_plugins,
    running_plugin_tools,
    shutdown_plugins,
)
from ravencode.runtime.tools.definitions import MODULE_TOOLS

API_IMPORT = "from ravencode.runtime.plugins import Plugin\n\n"
_SECRETISH = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSPHRASE", re.I)


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """The registry, the once-per-process flag and the tool-surface cache are process globals."""

    def reset() -> None:
        plugins_mod._plugin_registry = None
        plugins_mod._plugins_attempted = False
        plugins_mod._plugins_loop = None
        # the real invalidation, so a plugin tool left here cannot look like a built-in to the next test
        registry_mod.invalidate_plugin_tools()

    reset()
    yield
    reset()


@contextlib.contextmanager
def _warnings() -> Iterator[list[str]]:
    records: list[str] = []
    sink = logger.add(records.append, level="WARNING")
    try:
        yield records
    finally:
        logger.remove(sink)


def _plugin(name: str = "p1", tools: dict[str, Any] | None = None, source: str | None = None) -> Plugin:
    return Plugin(
        name=name,
        tools=tools or {"do": {"name": "do", "description": "d", "parameters": {}}},
        _source_path=source,
    )


def _returns(value: Any) -> Any:
    """A stand-in for `_load_untrusted_plugin`, which is a coroutine function."""

    async def _load(_plugin_dir: Path) -> Any:
        return value

    return _load


def _write_plugin(root: Path, dir_name: str, body: str) -> Path:
    plugin_dir = root / dir_name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(API_IMPORT + textwrap.dedent(body), encoding="utf-8")
    return plugin_dir


def _isolated_fs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Move cwd and home into tmp and drop env overrides, so the resolver answers about this fixture.

    Without this the checkout's own legacy `plugins/` layer is on the list on every machine that has one
    (this repository does: `plugins/example-http`), and a resolver assertion would be measuring the repo.
    """
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for key in ("PLUGINS_DIR", "RAVEN_PLUGINS_DIR", "RAVEN_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


# --- the host-side Plugin object --------------------------------------------------------------


class TestPlugin:
    def test_load_and_unload_call_the_callbacks(self) -> None:
        calls: list[str] = []
        p = Plugin(name="x", on_load=lambda: calls.append("load"), on_unload=lambda: calls.append("unload"))
        p.load()
        p.unload()
        assert calls == ["load", "unload"]

    def test_callbacks_are_optional(self) -> None:
        p = Plugin(name="x")
        p.load()
        p.unload()
        assert p.version == "0.1.0"
        assert p.tools == {}
        assert p._source_path is None


class TestRegistry:
    def test_register_and_get(self) -> None:
        reg = PluginRegistry()
        p = _plugin("a")
        reg.register(p)
        assert reg.get_plugin("a") is p
        assert reg.get_plugin("missing") is None

    def test_a_duplicate_name_keeps_the_first(self) -> None:
        reg = PluginRegistry()
        first = _plugin("a")
        reg.register(first)
        with _warnings() as records:
            reg.register(_plugin("a", tools={"other": {"name": "other", "description": "d", "parameters": {}}}))
        assert reg.get_plugin("a") is first
        assert reg.get_tool_owner("other") is None
        assert [line for line in records if "already registered" in line], records

    def test_the_tool_map_tracks_ownership(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        assert reg.get_tool_owner("do") == "a"
        assert reg.get_tool_owner("nope") is None

    def test_registering_tracks_the_source_file(self, tmp_path: Path) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("# x", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        assert reg._file_mtimes[str(f)] == f.stat().st_mtime

    def test_tracking_a_missing_file_is_silent(self, tmp_path: Path) -> None:
        reg = PluginRegistry()
        reg._track_file(str(tmp_path / "nope.py"))
        assert reg._file_mtimes == {}

    def test_tracking_an_unreadable_file_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(self: Path) -> bool:
            raise OSError("denied")

        monkeypatch.setattr(Path, "is_file", boom)
        reg = PluginRegistry()
        reg._track_file("/x/plugin.py")
        assert reg._file_mtimes == {}

    def test_unregister_drops_the_tools(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        reg.unregister("a")
        assert reg.get_plugin("a") is None
        assert reg.get_tool_owner("do") is None

    def test_unregister_unknown_is_a_noop(self) -> None:
        PluginRegistry().unregister("nope")

    def test_all_tools_and_the_plugins_copy(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        reg.register(_plugin("b", tools={"t2": {"name": "t2", "description": "d", "parameters": {}}}))
        assert set(reg.all_tools()) == {"do", "t2"}
        copied = reg.plugins
        copied.pop("a")
        assert "a" in reg.plugins

    def test_register_and_unregister_invalidate_the_tool_surface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalidating at the mutation site is what keeps a retracted plugin off the surface."""
        seen: list[str] = []
        monkeypatch.setattr(plugins_mod, "_invalidate_tool_surface", lambda: seen.append("x"))
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        reg.unregister("a")
        reg.register(_plugin("a"))
        reg.unregister("nope")
        assert seen == ["x", "x", "x"]


class TestToolSurface:
    def _surface_names(self) -> set[str]:
        return {d["function"]["name"] for d in registry_mod.get_tool_definitions()}

    def test_a_registered_plugin_reaches_the_surface_and_a_retracted_one_does_not(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolated_fs(monkeypatch, tmp_path)
        tool = {"surf.tool": {"name": "surf.tool", "description": "d", "parameters": {"type": "object"}}}
        reg = get_plugin_registry()
        reg.register(_plugin("surf", tools=tool))
        assert "surf.tool" in self._surface_names()
        assert MODULE_TOOLS["surf.tool"] is tool["surf.tool"]
        reg.unregister("surf")
        assert "surf.tool" not in self._surface_names()
        assert "surf.tool" not in MODULE_TOOLS

    def test_a_plugin_cannot_overwrite_a_built_in_tool(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _isolated_fs(monkeypatch, tmp_path)
        builtin = MODULE_TOOLS["read"]
        reg = get_plugin_registry()
        reg.register(_plugin("clash", tools={"read": {"name": "read", "description": "mine", "parameters": {}}}))
        with _warnings() as records:
            registry_mod.get_tool_definitions()
        assert MODULE_TOOLS["read"] is builtin
        assert [line for line in records if "already a built-in tool" in line], records
        reg.unregister("clash")


# --- hot reload -------------------------------------------------------------------------------


class TestWatchAndReload:
    async def test_watch_polls_and_stop_cancels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reg = PluginRegistry()
        polls = 0

        async def _count() -> None:
            nonlocal polls
            polls += 1

        monkeypatch.setattr(reg, "_check_reload", _count)
        await reg.watch(interval=0.01)
        first = reg._watch_task
        assert first is not None
        assert not first.done()
        await reg.watch(interval=0.01)
        assert reg._watch_task is first
        await asyncio.sleep(0.06)
        assert polls >= 2
        await reg.stop_watch()
        assert reg._watch_task is None
        await reg.stop_watch()

    async def test_a_changed_mtime_reloads_the_plugin(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("v1", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        reloaded = _plugin(
            "a",
            tools={"new": {"name": "new", "description": "d", "parameters": {}}},
            source=str(f),
        )
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin", _returns(reloaded))
        # the watcher compares against the mtime recorded at registration; move it back by a second
        reg._file_mtimes[str(f)] -= 1.0
        await reg._check_reload()
        assert reg.get_plugin("a") is reloaded
        assert reg._file_mtimes[str(f)] == f.stat().st_mtime
        assert reg.get_tool_owner("new") == "a"

    async def test_an_unreadable_tracked_file_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(self: Path) -> bool:
            raise OSError("denied")

        monkeypatch.setattr(Path, "is_file", boom)
        reg = PluginRegistry()
        reg._file_mtimes["/x/plugin.py"] = 1.0
        await reg._check_reload()
        assert reg._file_mtimes == {"/x/plugin.py": 1.0}

    async def test_reload_needs_a_registered_plugin_with_a_source(self, tmp_path: Path) -> None:
        reg = PluginRegistry()
        await reg._reload_plugin("nobody")
        reg.register(_plugin("no-path"))
        await reg._reload_plugin("no-path")
        assert reg.get_plugin("no-path") is not None
        gone = _plugin("vanished", source=str(tmp_path / "not-here.py"))
        reg.register(gone)
        await reg._reload_plugin("vanished")
        assert reg.get_plugin("vanished") is gone

    async def test_a_plugin_that_fails_to_reload_loses_its_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The old version is dropped: the worker re-executes the file on every call, so the tools the
        surface still advertised could not have run anyway. Silence would be worse."""
        f = tmp_path / "plugin.py"
        f.write_text("broken", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))

        async def _boom(_path: Path) -> Plugin:
            raise RuntimeError("register() timed out")

        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin", _boom)
        with _warnings() as records:
            await reg._reload_plugin("a")
        assert reg.get_plugin("a") is None
        assert reg.get_tool_owner("do") is None
        assert [line for line in records if "reload failed for a" in line], records

    async def test_a_reload_that_reports_no_plugin_also_unregisters(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("x", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin", _returns(None))
        await reg._reload_plugin("a")
        assert reg.get_plugin("a") is None

    def test_find_plugin_by_source(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", source="/x/plugin.py"))
        assert reg._find_plugin_by_source("/x/plugin.py") == "a"
        assert reg._find_plugin_by_source("/other") is None


# --- one directory contract --------------------------------------------------------------------


class TestPluginDirectories:
    def test_an_explicit_directory_wins_and_is_resolved(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / ".." / "plugins"
        assert plugin_directories(str(target)) == [(tmp_path / "plugins").resolve()]

    def test_no_directory_on_disk_means_no_directories(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _isolated_fs(monkeypatch, tmp_path)
        assert plugin_directories() == []
        assert plugin_files() == []

    def test_the_project_layer_is_read(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _isolated_fs(monkeypatch, tmp_path)
        team = base / ".raven" / "plugins"
        personal = base / ".raven.local" / "plugins"
        team.mkdir(parents=True)
        personal.mkdir(parents=True)
        assert plugin_directories() == [personal, team]

    def test_the_environment_layer_comes_first(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _isolated_fs(monkeypatch, tmp_path)
        team = base / ".raven" / "plugins"
        team.mkdir(parents=True)
        a = base / "a"
        b = base / "b"
        a.mkdir()
        b.mkdir()
        monkeypatch.setenv("PLUGINS_DIR", f"{a};{b}")
        assert plugin_directories() == [a, b, team]
        monkeypatch.setenv("RAVEN_PLUGINS_DIR", str(b))
        assert plugin_directories()[0] == b

    def test_raven_json_paths_are_honoured(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _isolated_fs(monkeypatch, tmp_path)
        from_config = base / "from-config"
        from_config.mkdir()
        team = base / ".raven" / "plugins"
        team.mkdir(parents=True)
        (base / "raven.json").write_text(json.dumps({"paths": {"plugins": "from-config"}}), encoding="utf-8")
        assert plugin_directories() == [from_config, team]

    def test_the_legacy_directory_is_still_read(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _isolated_fs(monkeypatch, tmp_path)
        legacy = base / "plugins"
        legacy.mkdir()
        assert plugin_directories() == [legacy]


class TestPluginFiles:
    def test_only_directories_with_a_plugin_py_are_found(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        (tmp_path / "empty").mkdir()
        _write_plugin(tmp_path, "real", "def register():\n    return Plugin(name='real')\n")
        found = plugin_files(tmp_path)
        assert [p.parent.name for p in found] == ["real"]
        assert found[0].name == "plugin.py"

    def test_a_name_is_taken_from_the_first_layer_that_has_it(self, tmp_path: Path) -> None:
        one = _write_plugin(tmp_path / "one", "dup", "def register():\n    return Plugin(name='dup')\n")
        two = _write_plugin(tmp_path / "two", "dup", "def register():\n    return Plugin(name='dup')\n")
        (tmp_path / "two" / "notaplugin").mkdir()
        assert plugins_mod._plugin_files([one.parent, two.parent]) == [one / "plugin.py"]
        assert plugins_mod._plugin_files([two.parent, one.parent]) == [two / "plugin.py"]

    def test_an_empty_directory(self, tmp_path: Path) -> None:
        assert plugin_files(tmp_path) == []


# --- the boundary to the worker (mocked here, unmocked below) ----------------------------------


class TestLoadUntrustedPlugin:
    async def test_tool_metadata_is_namespaced_by_the_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        reported = {
            "name": "weather",
            "tools": [
                {"name": "get_forecast", "dangerous": True, "description": "d", "parameters": {"type": "object"}},
                {"name": "bare"},
            ],
        }
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def _register(path: Path, **kwargs: Any) -> dict[str, Any]:
            return reported

        async def _call(plugin_file: str, tool: str, args: dict[str, Any], **kwargs: Any) -> str:
            calls.append((plugin_file, tool, args))
            return "called"

        monkeypatch.setattr("raven.core.plugin_loader.register_untrusted_plugin", _register)
        monkeypatch.setattr("raven.core.plugin_loader.call_untrusted_tool", _call)
        plugin_dir = tmp_path / "weather"
        plugin = await plugins_mod._load_untrusted_plugin(plugin_dir)
        assert plugin is not None
        assert set(plugin.tools) == {"weather.get_forecast", "weather.bare"}
        assert plugin.tools["weather.get_forecast"]["dangerous"] is True
        assert plugin.tools["weather.bare"] == {
            "name": "weather.bare",
            "dangerous": False,
            "description": "",
            "parameters": {},
            "handler": plugin.tools["weather.bare"]["handler"],
        }
        assert plugin._source_path == str(plugin_dir / "plugin.py")
        assert await plugin.tools["weather.get_forecast"]["handler"](city="Oslo") == "called"
        # the worker is addressed by file and by its own un-prefixed tool name
        assert calls == [(str(plugin_dir / "plugin.py"), "get_forecast", {"city": "Oslo"})]

    async def test_a_worker_that_refuses_yields_no_plugin(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def _none(path: Path, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr("raven.core.plugin_loader.register_untrusted_plugin", _none)
        assert await plugins_mod._load_untrusted_plugin(tmp_path / "x") is None


class TestDiscoveryAndRegistration:
    async def test_discover_skips_failures_and_keeps_order(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_plugin(tmp_path, "a", "def register():\n    return Plugin(name='a')\n")
        _write_plugin(tmp_path, "b", "def register():\n    return Plugin(name='b')\n")
        _write_plugin(tmp_path, "c", "def register():\n    return Plugin(name='c')\n")

        async def _load(plugin_dir: Path) -> Plugin | None:
            if plugin_dir.name == "b":
                raise RuntimeError("register() timed out")
            if plugin_dir.name == "c":
                return None
            return Plugin(name=plugin_dir.name)

        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin", _load)
        found = await discover_plugins(tmp_path)
        assert [p.name for p in found] == ["a"]

    async def test_register_all_fills_the_registry_and_can_watch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def _discover(_dir: Any = None) -> list[Plugin]:
            return [_plugin("a"), _plugin("b")]

        monkeypatch.setattr(plugins_mod, "discover_plugins", _discover)
        assert await register_all_plugins(tmp_path, watch=True) == 2
        reg = get_plugin_registry()
        assert set(reg.plugins) == {"a", "b"}
        assert reg._watch_task is not None
        await reg.stop_watch()

    async def test_ensure_runs_once_per_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runs = 0

        async def _register(_dir: Any = None, watch: bool = False) -> int:
            nonlocal runs
            runs += 1
            return 1

        monkeypatch.setattr(plugins_mod, "register_all_plugins", _register)
        assert await ensure_plugin_tools() == 1
        assert await ensure_plugin_tools() == 0
        assert runs == 1
        assert await ensure_plugin_tools(force=True) == 1
        assert runs == 2

    async def test_a_broken_discovery_is_reported_once_and_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _boom(_dir: Any = None, watch: bool = False) -> int:
            raise OSError("plugins directory is a file")

        monkeypatch.setattr(plugins_mod, "register_all_plugins", _boom)
        with _warnings() as records:
            assert await ensure_plugin_tools() == 0
        assert [line for line in records if "Plugin discovery unavailable" in line], records
        assert await ensure_plugin_tools() == 0

    async def test_the_context_manager_brackets_registration_and_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []

        async def _ensure(*, watch: bool = False, force: bool = False) -> int:
            events.append("ensure")
            return 0

        async def _shutdown() -> None:
            events.append("shutdown")

        monkeypatch.setattr(plugins_mod, "ensure_plugin_tools", _ensure)
        monkeypatch.setattr(plugins_mod, "shutdown_plugins", _shutdown)
        async with running_plugin_tools():
            events.append("body")
        assert events == ["ensure", "body", "shutdown"]
        events.clear()
        with pytest.raises(RuntimeError):
            async with running_plugin_tools():
                raise RuntimeError("boom")
        assert events == ["ensure", "shutdown"]

    async def test_shutdown_stops_the_watcher_and_every_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[str] = []
        reg = get_plugin_registry()

        async def _stop_watch() -> None:
            events.append("watch")

        async def _stop_workers() -> None:
            events.append("workers")

        monkeypatch.setattr(reg, "stop_watch", _stop_watch)
        monkeypatch.setattr("raven.core.plugin_loader.stop_untrusted_plugins", _stop_workers)
        await shutdown_plugins()
        assert events == ["watch", "workers"]


class TestSurfaceIsNotSilent:
    def test_the_helper_names_what_the_registry_never_loaded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _files(_dir: Any = None) -> list[Path]:
            return [tmp_path / "waiting" / "plugin.py"]

        monkeypatch.setattr(plugins_mod, "plugin_files", _files)
        assert registry_mod._unregistered_plugins_on_disk() == ["waiting"]
        get_plugin_registry().register(_plugin("loaded"))
        assert registry_mod._unregistered_plugins_on_disk() == []

    def test_an_unreadable_directory_does_not_become_a_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_dir: Any = None) -> list[Path]:
            raise OSError("denied")

        monkeypatch.setattr(plugins_mod, "plugin_files", _boom)
        assert registry_mod._unregistered_plugins_on_disk() == []

    def test_getting_the_surface_warns_about_plugins_that_could_not_be_loaded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _files(_dir: Any = None) -> list[Path]:
            return [tmp_path / "plugins" / "dropped" / "plugin.py"]

        monkeypatch.setattr(plugins_mod, "plugin_files", _files)
        with _warnings() as records:
            registry_mod.get_tool_definitions()
        offenders = [line for line in records if "not on the tool surface" in line]
        assert offenders and "dropped" in offenders[0], records


# --- the real sandbox, unmocked ----------------------------------------------------------------
#
# Every test below starts a real `python -P raven/core/plugin_worker.py` child. Measured cost: about
# 0.17 s per worker, so this whole class costs a few seconds and proves what no mock can — that the
# protocol, the import guard and the capability round-trip work end to end.


class TestSandboxEndToEnd:
    @pytest.fixture(autouse=True)
    async def _reap_workers(self) -> AsyncIterator[None]:
        yield
        await shutdown_plugins()

    async def test_a_real_plugin_loads_and_its_tool_runs(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "counter",
            """
            def register(ctx=None):
                async def count_words(text: str) -> str:
                    return str(len(text.split()))
                return Plugin(name="counter", version="1.2.3", tools={
                    "count_words": {
                        "name": "count_words",
                        "dangerous": False,
                        "description": "Count the words in a string.",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string", "description": "Text"}},
                            "required": ["text"],
                        },
                        "handler": count_words,
                    }
                })
            """,
        )
        found = await discover_plugins(tmp_path)
        assert [p.name for p in found] == ["counter"]
        tool = found[0].tools["counter.count_words"]
        assert tool["description"] == "Count the words in a string."
        assert tool["parameters"]["required"] == ["text"]
        assert await tool["handler"](text="one two three") == "3"
        # a second call reuses the same child interpreter rather than paying for a new one
        assert await tool["handler"](text="four") == "1"

    async def test_non_ascii_survives_the_pipe(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "cyr",
            """
            def register(ctx=None):
                async def say(text: str) -> str:
                    return f"Привет {text}"
                return Plugin(name="cyr", tools={"say": {"name": "say", "description": "d",
                    "parameters": {"type": "object"}, "handler": say}})
            """,
        )
        found = await discover_plugins(tmp_path)
        assert await found[0].tools["cyr.say"]["handler"](text="мир") == "Привет мир"

    async def test_a_capability_round_trip_is_answered_by_the_host(self, tmp_path: Path) -> None:
        """The plugin cannot open a socket; it asks, and the host's SSRF check is what answers."""
        _write_plugin(
            tmp_path,
            "fetcher",
            """
            def register(ctx=None):
                async def grab(url: str) -> str:
                    return await ctx.safe_http("GET", url)
                return Plugin(name="fetcher", tools={"grab": {"name": "grab", "description": "d",
                    "parameters": {"type": "object"}, "handler": grab}})
            """,
        )
        found = await discover_plugins(tmp_path)
        out = await found[0].tools["fetcher.grab"]["handler"](url="http://169.254.169.254/latest/meta-data")
        assert out.startswith("[blocked]"), out

    async def test_a_capability_cannot_write_outside_the_workspace(self, tmp_path: Path) -> None:
        from raven.core.workspace import workspace_root

        outside = str(workspace_root().parent / "definitely-outside-the-workspace.txt")
        _write_plugin(
            tmp_path,
            "writer",
            """
            def register(ctx=None):
                async def put(path: str, content: str) -> str:
                    return await ctx.safe_file_write(path, content)
                return Plugin(name="writer", tools={"put": {"name": "put", "description": "d",
                    "parameters": {"type": "object"}, "handler": put}})
            """,
        )
        found = await discover_plugins(tmp_path)
        out = await found[0].tools["writer.put"]["handler"](path=outside, content="x")
        assert out.startswith("[error] PermissionError: Access denied"), out
        assert not (workspace_root().parent / "definitely-outside-the-workspace.txt").exists()

    async def test_an_unknown_capability_is_refused_by_the_host(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "greedy",
            """
            def register(ctx=None):
                async def ask(text: str) -> str:
                    return await ctx._request_capability("spawn_process", cmd=text)
                return Plugin(name="greedy", tools={"ask": {"name": "ask", "description": "d",
                    "parameters": {"type": "object"}, "handler": ask}})
            """,
        )
        found = await discover_plugins(tmp_path)
        assert await found[0].tools["greedy.ask"]["handler"](text="whoami") == "[denied] capability not available"

    async def test_a_slow_register_is_cut_off(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "sleeper",
            """
            import time

            def register(ctx=None):
                time.sleep(5)
                return Plugin(name="sleeper", tools={})
            """,
        )
        with _warnings() as records:
            assert await discover_plugins(tmp_path) == []
        assert records  # `time` is allowed, so this reaches the 2 s register budget and is logged

    async def test_a_broken_or_non_plugin_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "syntax").mkdir()
        (tmp_path / "syntax" / "plugin.py").write_text("def :\n", encoding="utf-8")
        (tmp_path / "nolib").mkdir()
        (tmp_path / "nolib" / "plugin.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "raises").mkdir()
        (tmp_path / "raises" / "plugin.py").write_text("raise RuntimeError('no')\n", encoding="utf-8")
        assert await discover_plugins(tmp_path) == []

    async def test_a_directory_without_plugin_py_is_not_a_plugin(self, tmp_path: Path) -> None:
        (tmp_path / "notes").write_text("x", encoding="utf-8")
        assert await discover_plugins(tmp_path) == []


class TestSandboxRefusals:
    """What the child says no to, read from the worker's own protocol reply."""

    @pytest.fixture(autouse=True)
    async def _reap_workers(self) -> AsyncIterator[None]:
        yield
        await shutdown_plugins()

    async def _register_reply(self, tmp_path: Path, dir_name: str, body: str) -> dict[str, Any]:
        from raven.core.plugin_loader import WorkerProcess

        plugin_dir = _write_plugin(tmp_path, dir_name, body)
        worker = WorkerProcess(plugin_dir / "plugin.py")
        try:
            return await worker.send_command(
                {"type": "register", "path": str(plugin_dir / "plugin.py"), "register_timeout": 2.0},
                timeout=6.0,
            )
        finally:
            await worker.stop()

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("import os\n\ndef register():\n    return Plugin(name='x', tools={})\n", "blocked"),
            ("import subprocess\n\ndef register():\n    return Plugin(name='x', tools={})\n", "blocked"),
            ("from raven.core import config\n\ndef register():\n    return Plugin(name='x', tools={})\n", "blocked"),
            ("__import__('httpx')\n\ndef register():\n    return Plugin(name='x', tools={})\n", "blocked"),
            ("from . import helper\n\ndef register():\n    return Plugin(name='x', tools={})\n", "relative"),
            ("open('/etc/passwd')\n\ndef register():\n    return Plugin(name='x', tools={})\n", "open"),
            ("getattr(os, 'system')\n\ndef register():\n    return Plugin(name='x', tools={})\n", "getattr"),
            ("x = compile('1', '<s>', 'eval')\n\ndef register():\n    return Plugin(name='x', tools={})\n", "compile"),
            ("exec('x = 1')\n\ndef register():\n    return Plugin(name='x', tools={})\n", "exec"),
        ],
    )
    async def test_the_guard_says_no(self, tmp_path: Path, body: str, expected: str) -> None:
        resp = await self._register_reply(tmp_path, f"no{abs(hash(body)) % 1000}", body)
        assert resp["type"] == "error", resp
        assert expected in resp["error"], resp["error"]

    async def test_the_allowed_imports_are_the_documented_ones(self, tmp_path: Path) -> None:
        resp = await self._register_reply(
            tmp_path,
            "yes",
            """
            import json, re, math, datetime, base64, hashlib, uuid, statistics, collections
            from urllib.parse import urlparse
            from dataclasses import dataclass

            def register():
                return Plugin(name='yes', tools={})
            """,
        )
        assert resp["type"] == "register_ok", resp

    async def test_the_plugin_api_import_is_a_shim_not_the_host_module(self, tmp_path: Path) -> None:
        """`Plugin.__init__.__globals__` is the namespace the worker built, so the host's Path is not in it."""
        resp = await self._register_reply(
            tmp_path,
            "reach",
            """
            def register():
                g = Plugin.__init__.__globals__
                raise RuntimeError("globals=" + repr(sorted(g)))
            """,
        )
        assert resp["type"] == "error"
        assert resp["error"] == "globals=['Plugin', '__builtins__']", resp["error"]

    async def test_reaching_a_host_file_through_the_api_class_fails(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "readsecret",
            """
            def register(ctx=None):
                async def read(target: str) -> str:
                    g = Plugin.__init__.__globals__
                    return g["Path"](target).read_text()
                return Plugin(name="readsecret", tools={"read": {"name": "read", "description": "d",
                    "parameters": {"type": "object"}, "handler": read}})
            """,
        )
        found = await discover_plugins(tmp_path)
        with pytest.raises(RuntimeError, match=r"not defined|Path"):
            await found[0].tools["readsecret.read"]["handler"](target="D:/raven/data/web_secret_key")

    def test_the_shim_namespace_holds_no_credential_paths(self) -> None:
        import raven.core.plugin_worker as worker_mod

        module = worker_mod._plugin_api_module()
        assert set(k for k in module.__dict__ if not k.startswith("__")) == {"Plugin"}
        namespace = module.Plugin.__init__.__globals__
        assert "Path" not in namespace and "asyncio" not in namespace and "sys" not in namespace
        builtins_ = namespace["__builtins__"]
        assert isinstance(builtins_, dict)
        for name in ("open", "exec", "eval", "compile", "getattr", "input"):
            assert name not in builtins_, name
        with pytest.raises(ImportError, match="blocked"):
            builtins_["__import__"]("os")

    def test_the_worker_child_gets_no_secrets_and_no_path_to_the_source_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from raven.core.plugin_loader import _WORKER_ENV_KEYS, _worker_env

        root = Path(__file__).resolve().parents[1]
        script = root / "raven" / "core" / "plugin_worker.py"
        outside = tmp_path / "deps"
        outside.mkdir()
        monkeypatch.setenv("SOME_API_KEY", "leak-me")
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(root), str(root / "libs"), str(outside), str(script)]))
        env = _worker_env(script)
        assert [k for k in env if _SECRETISH.search(k)] == [], sorted(env)
        assert "SOME_API_KEY" not in env
        assert {k.upper() for k in env} <= _WORKER_ENV_KEYS | {"PYTHONPATH"}
        # every entry that can import this app is gone, including subdirectories and the worker's own file
        assert env["PYTHONPATH"] == str(outside)

    def test_the_child_environment_keeps_the_interpreter_alive(self) -> None:
        """A filtered env is only safe if the worker still starts: proven by the tests above running."""
        from raven.core.plugin_loader import _WORKER_ENV_KEYS

        assert {"PATH", "SYSTEMROOT", "TEMP"} <= _WORKER_ENV_KEYS

    async def test_a_tool_that_raises_is_reported_as_an_error_not_a_hang(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "crash",
            """
            def register(ctx=None):
                async def go(text: str) -> str:
                    raise ValueError("bad input")
                return Plugin(name="crash", tools={"go": {"name": "go", "description": "d",
                    "parameters": {"type": "object"}, "handler": go}})
            """,
        )
        found = await discover_plugins(tmp_path)
        with pytest.raises(RuntimeError, match="bad input"):
            await found[0].tools["crash.go"]["handler"](text="x")

    async def test_an_unknown_tool_or_argument_mismatch_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "small",
            """
            def register(ctx=None):
                async def one(a: str) -> str:
                    return a
                return Plugin(name="small", tools={"one": {"name": "one", "description": "d",
                    "parameters": {"type": "object"}, "handler": one}})
            """,
        )
        found = await discover_plugins(tmp_path)
        plugin_file = str(tmp_path / "small" / "plugin.py")
        from raven.core.plugin_loader import call_untrusted_tool

        with pytest.raises(RuntimeError, match="unknown tool"):
            await call_untrusted_tool(plugin_file, "missing", {})
        with pytest.raises(RuntimeError, match="unexpected keyword argument"):
            await found[0].tools["small.one"]["handler"](b=2)
