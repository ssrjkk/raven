from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.runtime.plugins as plugins_mod
from ravencode.runtime.plugins import (
    Plugin,
    PluginRegistry,
    discover_plugins,
    get_plugin_registry,
    register_all_plugins,
    register_internal_plugins,
)


@pytest.fixture(autouse=True)
def reset() -> Generator[None, None, None]:
    plugins_mod._plugin_registry = None
    yield
    plugins_mod._plugin_registry = None


def _plugin(name: str = "p1", tools: dict[str, dict[str, object]] | None = None, source: str | None = None) -> Plugin:
    return Plugin(
        name=name,
        tools=tools or {"do": {"name": "do", "handler": lambda: "x"}},
        on_load=lambda: None,
        on_unload=lambda: None,
        _source_path=source,
    )


class TestPlugin:
    def test_load_calls_callback(self) -> None:
        calls: list[str] = []
        p = Plugin(name="x", on_load=lambda: calls.append("loaded"), on_unload=lambda: calls.append("unloaded"))
        p.load()
        p.unload()
        assert calls == ["loaded", "unloaded"]

    def test_load_without_callback(self) -> None:
        Plugin(name="x").load()
        Plugin(name="x").unload()

    def test_defaults(self) -> None:
        p = Plugin(name="x")
        assert p.version == "0.1.0"
        assert p.tools == {}
        assert p._source_path is None


class TestRegistry:
    def test_register_and_get(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        assert reg.get_plugin("a") is not None
        assert reg.get_plugin("missing") is None

    def test_register_duplicate_warns(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        reg.register(_plugin("a"))
        assert len(reg.plugins) == 1

    def test_register_tracks_tools(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", tools={"t1": {"name": "t1"}}))
        assert reg.get_tool_owner("t1") == "a"
        assert reg.get_tool_owner("nope") is None

    def test_register_tracks_source_file(self, tmp_path) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("# x", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        assert str(f) in reg._file_mtimes

    def test_unregister(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", tools={"t1": {"name": "t1"}}))
        reg.unregister("a")
        assert reg.get_plugin("a") is None
        assert reg.get_tool_owner("t1") is None

    def test_unregister_unknown_noop(self) -> None:
        PluginRegistry().unregister("nope")

    def test_all_tools(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", tools={"t1": {"name": "t1"}}))
        reg.register(_plugin("b", tools={"t2": {"name": "t2"}}))
        assert set(reg.all_tools()) == {"t1", "t2"}

    def test_plugins_property_copy(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        copy = reg.plugins
        copy.pop("a")
        assert "a" in reg.plugins

    def test_set_on_reload(self) -> None:
        reg = PluginRegistry()
        cb = lambda name: None  # noqa: E731
        reg.set_on_reload(cb)
        assert reg._on_reload is cb

    def test_track_file_missing(self, tmp_path) -> None:
        reg = PluginRegistry()
        reg._track_file(str(tmp_path / "nope.py"))
        assert reg._file_mtimes == {}

    def test_track_file_oserror(self, tmp_path, monkeypatch) -> None:
        reg = PluginRegistry()
        monkeypatch.setattr(Path, "is_file", MagicMock(side_effect=OSError("boom")))
        reg._track_file(str(tmp_path / "x.py"))
        assert reg._file_mtimes == {}

    async def test_watch_and_stop(self, monkeypatch) -> None:
        reg = PluginRegistry()
        calls = 0

        async def sleeper(interval: float) -> None:
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr("ravencode.runtime.plugins.asyncio.sleep", sleeper)
        await reg.watch()
        assert reg._watch_task is not None
        await reg.watch()
        task = reg._watch_task
        await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await task
        await reg.stop_watch()
        assert reg._watch_task is None

    async def test_stop_watch_when_none(self) -> None:
        reg = PluginRegistry()
        await reg.stop_watch()

    async def test_check_reload_detects_change(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("v1", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        old = reg._file_mtimes[str(f)]
        f.write_text("v2", encoding="utf-8")
        old_mtime = reg._file_mtimes[str(f)]
        # force different mtime
        reg._file_mtimes[str(f)] = old_mtime - 1
        monkeypatch.setattr(plugins_mod, "_load_plugin_from_file", lambda path: _plugin("a", source=str(path)))
        assert old != reg._file_mtimes[str(f)]
        await reg._check_reload()
        assert reg._file_mtimes[str(f)] == f.stat().st_mtime

    async def test_check_reload_oserror(self, tmp_path, monkeypatch) -> None:
        reg = PluginRegistry()
        reg._file_mtimes[str(tmp_path / "x")] = 1.0
        monkeypatch.setattr(Path, "is_file", MagicMock(side_effect=OSError("boom")))
        await reg._check_reload()

    def test_find_plugin_by_source(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", source="/x/plugin.py"))
        assert reg._find_plugin_by_source("/x/plugin.py") == "a"
        assert reg._find_plugin_by_source("/other") is None

    async def test_reload_plugin_no_plugin(self) -> None:
        await PluginRegistry()._reload_plugin("nope")

    async def test_reload_plugin_no_source(self) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a"))
        await reg._reload_plugin("a")

    async def test_reload_plugin_source_missing(self, tmp_path) -> None:
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(tmp_path / "nope.py")))
        await reg._reload_plugin("a")

    async def test_reload_plugin_success(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("# x", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        reloaded = MagicMock()
        reloaded._source_path = None
        reloaded.name = "a"
        reloaded.tools = {}
        monkeypatch.setattr(plugins_mod, "_load_plugin_from_file", lambda path: reloaded)
        events: list[str] = []
        reg.set_on_reload(lambda name: events.append(name))
        await reg._reload_plugin("a")
        assert reloaded._source_path == str(f)
        assert reg.get_plugin("a") is reloaded
        assert events == ["a"]

    async def test_reload_plugin_exception(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "plugin.py"
        f.write_text("# x", encoding="utf-8")
        reg = PluginRegistry()
        reg.register(_plugin("a", source=str(f)))
        monkeypatch.setattr(plugins_mod, "_load_plugin_from_file", MagicMock(side_effect=RuntimeError("boom")))
        await reg._reload_plugin("a")


class TestLoadFromFile:
    def test_valid_plugin(self, tmp_path) -> None:
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text(
            "from ravencode.runtime.plugins import Plugin\n"
            "def register():\n"
            "    return Plugin(name='filep')\n",
            encoding="utf-8",
        )
        plugin = plugins_mod._load_plugin_from_file(src)
        assert plugin is not None
        assert plugin.name == "filep"
        assert plugin._source_path == str(src)

    def test_no_register_function(self, tmp_path) -> None:
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text("x = 1\n", encoding="utf-8")
        assert plugins_mod._load_plugin_from_file(src) is None

    def test_register_returns_non_plugin(self, tmp_path) -> None:
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text("def register():\n    return 'nope'\n", encoding="utf-8")
        assert plugins_mod._load_plugin_from_file(src) is None

    def test_syntax_error(self, tmp_path) -> None:
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text("def :\n", encoding="utf-8")
        assert plugins_mod._load_plugin_from_file(src) is None

    def test_missing_file(self, tmp_path) -> None:
        assert plugins_mod._load_plugin_from_file(tmp_path / "nope.py") is None

    def test_no_spec(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("importlib.util.spec_from_file_location", MagicMock(return_value=None))
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text("# x", encoding="utf-8")
        assert plugins_mod._load_plugin_from_file(src) is None

    def test_generic_exception(self, tmp_path, monkeypatch) -> None:
        src = tmp_path / "p" / "plugin.py"
        src.parent.mkdir()
        src.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        assert plugins_mod._load_plugin_from_file(src) is None


class TestWorkerLoader:
    def test_result_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.plugins.asyncio.get_running_loop", MagicMock(side_effect=RuntimeError())
        )
        monkeypatch.setattr(
            "raven.core.plugin_loader.register_untrusted_plugin", AsyncMock(return_value=None)
        )
        assert plugins_mod._load_untrusted_plugin_via_worker(Path("x.py")) is None

    def test_result_with_tools(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.plugins.asyncio.get_running_loop", MagicMock(side_effect=RuntimeError())
        )
        result = {
            "name": "workerp",
            "tools": [
                {"name": "t1", "dangerous": True, "description": "d", "parameters": {"type": "object"}},
                {"name": "t2"},
            ],
        }
        monkeypatch.setattr("raven.core.plugin_loader.register_untrusted_plugin", AsyncMock(return_value=result))
        monkeypatch.setattr("raven.core.plugin_loader.call_untrusted_tool", AsyncMock(return_value="ok"))
        plugin = plugins_mod._load_untrusted_plugin_via_worker(Path("x.py"))
        assert plugin is not None
        assert plugin.name == "workerp"
        assert set(plugin.tools) == {"t1", "t2"}
        assert plugin.tools["t1"]["dangerous"] is True
        assert plugin.tools["t2"]["description"] == ""
        assert asyncio.run(plugin.tools["t1"]["handler"](a=1)) == "ok"

    def test_running_loop_branch(self, monkeypatch) -> None:
        fake_loop = SimpleNamespace(run_until_complete=MagicMock(return_value={"name": "lp", "tools": []}))
        monkeypatch.setattr("ravencode.runtime.plugins.asyncio.get_running_loop", lambda: fake_loop)
        plugin = plugins_mod._load_untrusted_plugin_via_worker(Path("x.py"))
        assert plugin is not None
        assert plugin.name == "lp"


def _neutralize_discover_dirs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))


class TestDiscoverPlugins:
    def test_empty_dir(self, tmp_path, monkeypatch) -> None:
        _neutralize_discover_dirs(monkeypatch, tmp_path)
        assert discover_plugins(tmp_path) == []

    def test_loads_plugin(self, tmp_path, monkeypatch) -> None:
        _neutralize_discover_dirs(monkeypatch, tmp_path)
        pdir = tmp_path / "p"
        pdir.mkdir()
        (pdir / "plugin.py").write_text("# x", encoding="utf-8")
        fake = MagicMock(return_value=Plugin(name="discovered"))
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin_via_worker", fake)
        found = discover_plugins(tmp_path)
        assert len(found) == 1
        assert found[0].name == "discovered"
        assert found[0]._source_path == str(pdir / "plugin.py")

    def test_duplicate_names_skipped(self, tmp_path, monkeypatch) -> None:
        base = tmp_path / "plugins"
        (base / "a").mkdir(parents=True)
        (base / "a" / "plugin.py").write_text("# x", encoding="utf-8")
        # plugins_dir and cwd/plugins point at the same dir -> "a" appears twice
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        fake = MagicMock(return_value=Plugin(name="dup"))
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin_via_worker", fake)
        found = discover_plugins(base)
        assert len(found) == 1

    def test_skips_files_and_dirs_without_plugin(self, tmp_path, monkeypatch) -> None:
        _neutralize_discover_dirs(monkeypatch, tmp_path)
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        (tmp_path / "empty").mkdir()
        (tmp_path / "ok").mkdir()
        (tmp_path / "ok" / "plugin.py").write_text("# x", encoding="utf-8")
        fake = MagicMock(return_value=Plugin(name="found"))
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin_via_worker", fake)
        found = discover_plugins(tmp_path)
        assert len(found) == 1
        assert found[0].name == "found"

    def test_loader_exception_skipped(self, tmp_path, monkeypatch) -> None:
        _neutralize_discover_dirs(monkeypatch, tmp_path)
        d = tmp_path / "a"
        d.mkdir()
        (d / "plugin.py").write_text("# x", encoding="utf-8")
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin_via_worker", MagicMock(side_effect=RuntimeError("x")))
        assert discover_plugins(tmp_path) == []

    def test_plugin_without_tools_skipped(self, tmp_path, monkeypatch) -> None:
        _neutralize_discover_dirs(monkeypatch, tmp_path)
        d = tmp_path / "a"
        d.mkdir()
        (d / "plugin.py").write_text("# x", encoding="utf-8")
        monkeypatch.setattr(plugins_mod, "_load_untrusted_plugin_via_worker", MagicMock(return_value=None))
        assert discover_plugins(tmp_path) == []


class TestRegisterAll:
    def test_no_loop(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.plugins.asyncio.get_running_loop", MagicMock(side_effect=RuntimeError())
        )
        monkeypatch.setattr(plugins_mod, "discover_plugins", lambda plugins_dir: [Plugin(name="a")])
        assert register_all_plugins(watch=True) == 1

    async def test_with_loop(self, monkeypatch) -> None:
        monkeypatch.setattr(plugins_mod, "discover_plugins", lambda plugins_dir: [])
        result = register_all_plugins(watch=True)
        assert result == 0


class TestRegisterInternal:
    def test_bridges_plugins(self, tmp_path, monkeypatch) -> None:
        tool = SimpleNamespace(name="it", description="d", parameters={}, handler=lambda: "h")

        def fake_load(entry):
            if entry.name == "boom":
                raise RuntimeError("x")
            if entry.name == "notools":
                return []
            return [tool]

        loader = MagicMock()
        loader.load_from_dir = MagicMock(side_effect=fake_load)
        monkeypatch.setattr("raven.core.plugin_loader.PluginLoader", lambda: loader)
        (tmp_path / "internal").mkdir()
        (tmp_path / "internal" / "plugin.py").write_text("# x", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        (tmp_path / "empty").mkdir()
        (tmp_path / "notools").mkdir()
        (tmp_path / "notools" / "plugin.py").write_text("# x", encoding="utf-8")
        (tmp_path / "boom").mkdir()
        (tmp_path / "boom" / "plugin.py").write_text("# x", encoding="utf-8")
        count = register_internal_plugins(str(tmp_path))
        assert count == 1
        assert get_plugin_registry().get_plugin("internal") is not None

    def test_default_base_dir(self, monkeypatch) -> None:
        loader = MagicMock()
        loader.load_from_dir = MagicMock(return_value=[])
        monkeypatch.setattr("raven.core.plugin_loader.PluginLoader", lambda: loader)
        count = register_internal_plugins()
        assert count == 0
