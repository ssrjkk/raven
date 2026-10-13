from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import plugin as plugin_mod

_CAT = SimpleNamespace(value="coding")
_STATUS = SimpleNamespace(value="installed")


def _installed() -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(name="p1", version="1.0", category=_CAT),
        status=_STATUS,
    )


def _search_item() -> SimpleNamespace:
    return SimpleNamespace(name="p1", version="1.0", category=_CAT, description="d" * 200)


def _info(tags: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        name="p1", version="1.0", author="a", category=_CAT, description="desc", tags=tags or []
    )


class _FakeManager:
    def __init__(
        self,
        installed: list[Any] | None = None,
        search: list[Any] | None = None,
        info: Any = None,
        uninstall_ok: bool = True,
        install_raises: bool = False,
    ) -> None:
        self._installed = installed if installed is not None else []
        self._search = search if search is not None else []
        self._info = info
        self._uninstall_ok = uninstall_ok
        self._install_raises = install_raises

    def list_installed(self) -> list[Any]:
        return self._installed

    def search_plugins(self, _q: str) -> list[Any]:
        return self._search

    async def install_plugin(self, _url: str, source: str = "remote") -> Any:
        if self._install_raises:
            raise RuntimeError("net fail")
        return SimpleNamespace(metadata=SimpleNamespace(name="p1", version="1.0"), status=_STATUS)

    def uninstall_plugin(self, _name: str) -> bool:
        return self._uninstall_ok

    def get_plugin_info(self, _name: str) -> Any:
        return self._info

    def get_installation_status(self, _name: str) -> Any:
        return _STATUS


class _FakeCatalog:
    def __init__(self, top: list[Any] | None = None, plugins: dict[str, Any] | None = None) -> None:
        self._top = top if top is not None else []
        self._plugins = plugins if plugins is not None else {}
        self.synced = 0

    async def sync(self) -> None:
        self.synced += 1

    def get_top_rated(self, _limit: int) -> list[Any]:
        return self._top


def _patch_manager(monkeypatch: pytest.MonkeyPatch, mgr: _FakeManager) -> None:
    monkeypatch.setattr(plugin_mod, "_get_manager", lambda: mgr)


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, cat: _FakeCatalog) -> None:
    monkeypatch.setattr(plugin_mod, "_get_catalog", lambda: cat)


class TestGetters:
    def test_get_manager_creates_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(plugin_mod, "_manager", None)
        seen: dict[str, int] = {}

        class _Cat:
            def __init__(self) -> None:
                seen["cat"] = seen.get("cat", 0) + 1

        class _Mgr:
            def __init__(self, catalog: Any = None) -> None:
                self.catalog = catalog

        monkeypatch.setattr(plugin_mod, "PluginCatalog", _Cat)
        monkeypatch.setattr(plugin_mod, "PluginManager", _Mgr)
        mgr = plugin_mod._get_manager()
        assert isinstance(mgr, _Mgr)
        assert mgr.catalog is not None
        assert plugin_mod._get_manager() is mgr

    def test_get_catalog_creates_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(plugin_mod, "_catalog", None)

        class _Cat:
            def __init__(self) -> None:
                return None

        monkeypatch.setattr(plugin_mod, "PluginCatalog", _Cat)
        cat = plugin_mod._get_catalog()
        assert isinstance(cat, _Cat)
        assert plugin_mod._get_catalog() is cat


class TestListAndSearch:
    def test_list_installed_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(installed=[]))
        assert plugin_mod.plugin_list_installed() == "[info] No plugins installed."

    def test_list_installed_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(installed=[_installed()]))
        out = plugin_mod.plugin_list_installed()
        assert "Installed plugins (1):" in out
        assert "p1 v1.0 [coding] status=installed" in out

    def test_search_no_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager())
        assert plugin_mod.plugin_search("") == "[info] Provide a search query."

    def test_search_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(search=[]))
        assert plugin_mod.plugin_search("x") == "[info] No plugins found for 'x'."

    def test_search_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(search=[_search_item()]))
        out = plugin_mod.plugin_search("x")
        assert "Plugin search results for 'x' (1):" in out
        assert "p1 v1.0 [coding]" in out


class TestInstallUninstall:
    @pytest.mark.asyncio
    async def test_install_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager())
        assert await plugin_mod.plugin_install("u") == "Installed 'p1' v1.0 (installed)"

    @pytest.mark.asyncio
    async def test_install_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(install_raises=True))
        assert "[error] Install failed" in await plugin_mod.plugin_install("u")

    @pytest.mark.asyncio
    async def test_uninstall_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(uninstall_ok=True))
        assert await plugin_mod.plugin_uninstall("p1") == "Uninstalled 'p1'."

    @pytest.mark.asyncio
    async def test_uninstall_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(uninstall_ok=False))
        assert await plugin_mod.plugin_uninstall("p1") == "[error] Plugin 'p1' not found."

    @pytest.mark.asyncio
    async def test_uninstall_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mgr = _FakeManager()

        def _raise(_n: str) -> bool:
            raise RuntimeError("boom")

        monkeypatch.setattr(mgr, "uninstall_plugin", _raise)
        _patch_manager(monkeypatch, mgr)
        assert "[error] Uninstall failed" in await plugin_mod.plugin_uninstall("p1")


class TestInfo:
    def test_info_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(info=None))
        assert plugin_mod.plugin_info("p1") == "[info] Plugin 'p1' not found."

    def test_info_with_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(info=_info(["a", "b"])))
        out = plugin_mod.plugin_info("p1")
        assert "Plugin: p1" in out
        assert "Tags: a, b" in out

    def test_info_no_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_manager(monkeypatch, _FakeManager(info=_info([])))
        assert "Tags: none" in plugin_mod.plugin_info("p1")


class TestCatalog:
    @pytest.mark.asyncio
    async def test_top_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_catalog(monkeypatch, _FakeCatalog(top=[]))
        assert await plugin_mod.plugin_catalog_top() == "[info] No rated plugins in catalog."

    @pytest.mark.asyncio
    async def test_top_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cat = _FakeCatalog(top=[(_search_item(), 4.56)])
        _patch_catalog(monkeypatch, cat)
        out = await plugin_mod.plugin_catalog_top()
        assert "Top rated plugins (1):" in out
        assert "★ 4.6" in out
        assert cat.synced == 1

    @pytest.mark.asyncio
    async def test_browse_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_catalog(monkeypatch, _FakeCatalog(plugins={}))
        assert await plugin_mod.plugin_catalog_browse() == "[info] No plugins in catalog."

    @pytest.mark.asyncio
    async def test_browse_category_no_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_catalog(monkeypatch, _FakeCatalog(plugins={"p1": _search_item()}))
        out = await plugin_mod.plugin_catalog_browse("voice")
        assert "for category voice" in out

    @pytest.mark.asyncio
    async def test_browse_with_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = _search_item()
        _patch_catalog(monkeypatch, _FakeCatalog(plugins={"p1": item}))
        out = await plugin_mod.plugin_catalog_browse("coding")
        assert "Catalog plugins (1):" in out
        assert "p1 v1.0 [coding]" in out


class TestRegistration:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        plugin_mod.register_plugin_tools(registry)
        for name in (
            "plugin_list_installed",
            "plugin_search",
            "plugin_install",
            "plugin_uninstall",
            "plugin_info",
            "plugin_catalog_top",
            "plugin_catalog_browse",
        ):
            assert registry.get(name) is not None
