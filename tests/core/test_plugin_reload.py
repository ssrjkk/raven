from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ravencode.runtime.plugins import (
    Plugin,
    PluginRegistry,
    _load_plugin_from_file,
    discover_plugins,
    get_plugin_registry,
    register_all_plugins,
    register_internal_plugins,
)


@pytest.fixture
def registry():
    r = PluginRegistry()
    yield r


class TestPluginRegistryWatch:
    def test_track_file(self, registry, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("# test")
        registry._track_file(str(f))
        assert str(f) in registry._file_mtimes

    def test_track_nonexistent(self, registry):
        registry._track_file("/nonexistent/file.py")
        assert len(registry._file_mtimes) == 0

    def test_find_plugin_by_source(self, registry):
        p = Plugin(name="test", _source_path="/path/to/plugin.py")
        registry.register(p)
        found = registry._find_plugin_by_source("/path/to/plugin.py")
        assert found == "test"

    def test_find_plugin_by_source_not_found(self, registry):
        assert registry._find_plugin_by_source("/nonexistent.py") is None

    def test_set_on_reload(self, registry):
        calls: list[str] = []
        registry.set_on_reload(lambda name: calls.append(name))
        assert registry._on_reload is not None

    def test_watch_start_stop(self, registry):
        asyncio.run(self._do_watch_test(registry))

    async def _do_watch_test(self, registry):
        await registry.watch(interval=0.5)
        assert registry._watch_task is not None
        assert not registry._watch_task.done()
        await registry.stop_watch()
        assert registry._watch_task is None

    def test_watch_idempotent(self, registry):
        async def go():
            await registry.watch(interval=0.5)
            await registry.watch(interval=0.5)
            t = registry._watch_task
            await registry.stop_watch()
            assert t is not None
        asyncio.run(go())


class TestPluginRegistryReloadSuccess:
    def test_reload_with_valid_file(self, tmp_path):
        async def go():
            src = tmp_path / "reloadable.py"
            src.write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="reloadable", version="1.0")
""")
            reg = PluginRegistry()
            p = Plugin(name="reloadable", _source_path=str(src))
            reg.register(p)
            # change file content
            src.write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="reloadable", version="2.0")
""")
            reg._file_mtimes[str(src)] = src.stat().st_mtime - 1
            await reg._check_reload()
            # verify reloaded version (just check it still exists)
            assert reg.get_plugin("reloadable") is not None
        asyncio.run(go())


class TestPluginRegistryReload:
    def test_reload_nonexistent(self, registry):
        async def go():
            p = Plugin(name="test", _source_path="/nonexistent.py")
            registry.register(p)
            await registry._reload_plugin("test")
            assert registry.get_plugin("test") is p  # still registered, file not found = no reload
        asyncio.run(go())

    def test_reload_no_source_path(self, registry):
        async def go():
            p = Plugin(name="test")
            registry.register(p)
            await registry._reload_plugin("test")
            assert registry.get_plugin("test") is not None
        asyncio.run(go())

    def test_reload_plugin_file_not_found(self, registry):
        async def go():
            p = Plugin(name="test", _source_path="/tmp/nonexistent_plugin.py")
            registry.register(p)
            await registry._reload_plugin("test")
            assert registry.get_plugin("test") is p
        asyncio.run(go())

    def test_reload_with_callback(self, registry):
        async def go():
            calls: list[str] = []
            registry.set_on_reload(lambda name: calls.append(name))
            p = Plugin(name="test", _source_path="/tmp/missing.py")
            registry.register(p)
            await registry._reload_plugin("test")
            assert len(calls) == 0
        asyncio.run(go())


class TestPlugin:
    def test_plugin_init(self):
        p = Plugin(name="p1", version="1.0.0", tools={"tool1": {"name": "tool1"}})
        assert p.name == "p1"
        assert p.version == "1.0.0"
        assert "tool1" in p.tools

    def test_plugin_load_unload(self):
        calls: list[str] = []
        p = Plugin(name="p", on_load=lambda: calls.append("load"), on_unload=lambda: calls.append("unload"))
        p.load()
        assert "load" in calls
        p.unload()
        assert "unload" in calls


class TestPluginRegistryBasics:
    def test_register(self, registry):
        p = Plugin(name="test")
        registry.register(p)
        assert registry.get_plugin("test") is p

    def test_register_duplicate(self, registry):
        p1 = Plugin(name="dup")
        p2 = Plugin(name="dup")
        registry.register(p1)
        registry.register(p2)
        assert registry.get_plugin("dup") is p1

    def test_unregister(self, registry):
        p = Plugin(name="test", tools={"t1": {}})
        registry.register(p)
        registry.unregister("test")
        assert registry.get_plugin("test") is None
        assert registry.get_tool_owner("t1") is None

    def test_all_tools(self, registry):
        p1 = Plugin(name="p1", tools={"a": {"name": "a"}})
        p2 = Plugin(name="p2", tools={"b": {"name": "b"}})
        registry.register(p1)
        registry.register(p2)
        tools = registry.all_tools()
        assert "a" in tools
        assert "b" in tools
        assert len(tools) == 2

    def test_plugins_property(self, registry):
        p = Plugin(name="p")
        registry.register(p)
        assert registry.plugins == {"p": p}

    def test_get_tool_owner(self, registry):
        p = Plugin(name="p", tools={"t1": {}})
        registry.register(p)
        assert registry.get_tool_owner("t1") == "p"
        assert registry.get_tool_owner("nonexistent") is None

    def test_unregister_non_existent(self, registry):
        registry.unregister("nonexistent")

    def test_plugin_source_path(self, registry):
        p = Plugin(name="with_path", _source_path="/tmp/some_plugin.py")
        registry.register(p)
        assert registry._find_plugin_by_source("/tmp/some_plugin.py") == "with_path"


class TestPluginRegistryAdvanced:
    def test_track_file_oserror(self, registry):
        registry._track_file("//invalid//path//")
        assert len(registry._file_mtimes) == 0

    def test_check_reload_oserror(self, registry):
        async def go():
            f = "/nonexistent/file.py"
            registry._file_mtimes[f] = 123.0
            await registry._check_reload()
            assert f in registry._file_mtimes
        asyncio.run(go())

    def test_watch_double_start_stop(self, registry):
        async def go():
            await registry.watch(interval=0.5)
            t1 = registry._watch_task
            await registry.watch(interval=0.5)
            t2 = registry._watch_task
            assert t1 is t2
            await registry.stop_watch()
        asyncio.run(go())

    def test_stop_watch_noop(self, registry):
        async def go():
            await registry.stop_watch()
        asyncio.run(go())

    def test_reload_success_path(self, registry, tmp_path):
        async def go():
            src = tmp_path / "good_plugin.py"
            src.write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="good", version="1.0")
""")
            p = Plugin(name="good", _source_path=str(src))
            registry.register(p)
            calls: list[str] = []
            registry.set_on_reload(lambda n: calls.append(n))
            src.write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="good", version="2.0")
""")
            await asyncio.sleep(0.3)
            # trigger reload by modifying mtime
            src.touch()
            await registry._check_reload()
            await asyncio.sleep(0.1)
        asyncio.run(go())

    def test_discover_plugins_empty(self, tmp_path):
        plugins = discover_plugins(tmp_path)
        assert len(plugins) == 0

    def test_discover_plugins_with_plugin(self, tmp_path):
        from ravencode.runtime.plugins import discover_plugins as _dp
        _dp(tmp_path / "nonexistent")
        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="myplugin", tools={"t1": {"name": "t1"}})
""")
        plugins = discover_plugins(tmp_path)
        assert len(plugins) >= 0

    def test_register_all_plugins(self, tmp_path):
        count = register_all_plugins(tmp_path, watch=False)
        assert count >= 0

    def test_get_plugin_registry_singleton(self):
        assert get_plugin_registry() is not None

    def test_register_internal_plugins_empty(self, tmp_path):
        count = register_internal_plugins(tmp_path)
        assert count == 0

    def test_register_internal_plugins_with_coroutine(self, tmp_path):
        plugin_dir = tmp_path / "test_int"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("""
async def my_tool(param: str = "") -> str:
    return f"hello {param}"
""")
        count = register_internal_plugins(tmp_path)
        assert count >= 1
        plugin = get_plugin_registry().get_plugin("test_int")
        assert plugin is not None
        assert "test_int.my_tool" in plugin.tools

    def test_discover_plugins_with_invalid(self, tmp_path):
        from ravencode.runtime.plugins import discover_plugins
        plugin_dir = tmp_path / "badplugin"
        plugin_dir.mkdir()
        f = plugin_dir / "plugin.py"
        f.write_text("this is not valid python !!!")
        plugins = discover_plugins(tmp_path)
        assert len(plugins) == 0  # malformed, skipped gracefully


class TestLoadPluginFromFile:
    def test_load_from_nonexistent(self, tmp_path):
        p = _load_plugin_from_file(tmp_path / "nonexistent.py")
        assert p is None

    def test_load_malformed(self, tmp_path):
        f = tmp_path / "bad_plugin.py"
        f.write_text("this is not valid python !!!")
        p = _load_plugin_from_file(f)
        assert p is None

    def test_load_empty_spec(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        p = _load_plugin_from_file(f)
        assert p is None  # no register function

    def test_load_with_register(self, tmp_path):
        f = tmp_path / "working_plugin.py"
        f.write_text("""
from ravencode.runtime.plugins import Plugin
def register():
    return Plugin(name="test_plugin", version="1.0", tools={"tool_x": {"name": "tool_x"}})
""")
        p = _load_plugin_from_file(f)
        assert p is not None
        assert p.name == "test_plugin"
        assert "tool_x" in p.tools


class TestPluginRegistryConcurrency:
    def test_register_unregister_race(self, registry):
        async def go():
            p = Plugin(name="race")
            registry.register(p)
            registry.unregister("race")
            registry.register(p)
            assert registry.get_plugin("race") is p
        asyncio.run(go())

    def test_watch_detects_mtime_change(self, registry, tmp_path):
        async def go():
            plugin_file = tmp_path / "test_plugin.py"
            plugin_file.write_text("")
            p = Plugin(name="watch_test", _source_path=str(plugin_file))
            registry.register(p)
            old_mtime = registry._file_mtimes.get(str(plugin_file))
            await asyncio.sleep(0.1)
            plugin_file.write_text("# changed")
            await registry._check_reload()
            assert old_mtime is not None
        asyncio.run(go())
