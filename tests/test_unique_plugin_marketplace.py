from __future__ import annotations

import json
from pathlib import Path

import pytest

from raven.unique.plugin_marketplace import (
    Category,
    InstallationStatus,
    InstalledPlugin,
    PluginCatalog,
    PluginManager,
    PluginMetadata,
    PluginRelease,
)


class TestEnums:
    def test_category_values(self) -> None:
        assert Category.CODING.value == "coding"
        assert Category.AUTOMATION.value == "automation"
        assert Category.UNIQUE.value == "unique"
        assert Category.VOICE.value == "voice"
        assert Category.CHANNEL.value == "channel"

    def test_installation_status_values(self) -> None:
        assert InstallationStatus.NOT_INSTALLED.value == "not_installed"
        assert InstallationStatus.INSTALLING.value == "installing"
        assert InstallationStatus.INSTALLED.value == "installed"
        assert InstallationStatus.FAILED.value == "failed"
        assert InstallationStatus.UPDATE_AVAILABLE.value == "update_available"


class TestDataclasses:
    def test_plugin_metadata_defaults(self) -> None:
        meta = PluginMetadata(id="p1", name="test-plugin", version="1.0.0")
        assert meta.description == ""
        assert meta.author == ""
        assert meta.tags == []
        assert meta.dependencies == []
        assert meta.icon == ""
        assert meta.category == Category.UNIQUE

    def test_plugin_metadata_with_category(self) -> None:
        meta = PluginMetadata(
            id="p2", name="coder", version="0.5.0", category=Category.CODING, tags=["python", "llm"]
        )
        assert meta.category == Category.CODING
        assert "python" in meta.tags

    def test_plugin_release_defaults(self) -> None:
        release = PluginRelease(version="1.0.0")
        assert release.download_url == ""
        assert release.checksum == ""
        assert release.min_raven_version == ""
        assert release.requires == []
        assert release.released_at == ""


class TestPluginCatalog:
    def setup_method(self) -> None:
        self.catalog = PluginCatalog()
        self.catalog._plugins = {
            "p1": PluginMetadata(id="p1", name="web-scraper", version="1.0.0", description="Scrape websites", category=Category.AUTOMATION, tags=["http", "scrape"]),
            "p2": PluginMetadata(id="p2", name="voice-transcriber", version="2.1.0", description="Transcribe voice", category=Category.VOICE, tags=["audio", "stt"]),
            "p3": PluginMetadata(id="p3", name="code-formatter", version="0.3.0", description="Format code", category=Category.CODING, tags=["python", "format"]),
        }
        self.catalog._ratings = {"p1": 4.5, "p2": 3.8, "p3": 4.2}
        self.catalog._downloads = {"p1": 1200, "p2": 800, "p3": 3500}

    def test_search_by_name(self) -> None:
        results = self.catalog.search("web")
        assert len(results) == 1
        assert results[0].id == "p1"

    def test_search_by_tag(self) -> None:
        results = self.catalog.search("audio")
        assert len(results) == 1
        assert results[0].id == "p2"

    def test_search_by_category(self) -> None:
        results = self.catalog.search("coding")
        assert len(results) == 1
        assert results[0].id == "p3"

    def test_search_returns_multiple(self) -> None:
        results = self.catalog.search("e")
        assert len(results) >= 2

    def test_search_empty_query(self) -> None:
        results = self.catalog.search("")
        assert len(results) == 3

    def test_search_no_match(self) -> None:
        results = self.catalog.search("zzzznotfound")
        assert results == []

    def test_get_top_rated(self) -> None:
        top = self.catalog.get_top_rated(2)
        assert len(top) == 2
        assert top[0][0].id == "p1"
        assert top[0][1] == 4.5

    def test_get_most_downloaded(self) -> None:
        top = self.catalog.get_most_downloaded(2)
        assert len(top) == 2
        assert top[0][0].id == "p3"
        assert top[0][1] == 3500

    def test_get_releases_empty(self) -> None:
        releases = self.catalog.get_releases("p1")
        assert releases == []

    def test_sync_no_url_falls_back(self) -> None:
        catalog = PluginCatalog()
        result = catalog._load_local_cache()
        assert result is False
        assert catalog._synced is False

    def test_add_local_plugin(self) -> None:
        meta = PluginMetadata(id="local-1", name="local-plugin", version="0.1.0")
        self.catalog.add_local_plugin(meta)
        assert "local-1" in self.catalog._plugins

    def test_sync_with_data(self) -> None:
        catalog = PluginCatalog()
        catalog._parse_catalog({
            "plugins": [
                {
                    "id": "sync-1",
                    "name": "sync-plugin",
                    "version": "1.0.0",
                    "category": "automation",
                    "rating": 4.0,
                    "downloads": 500,
                    "releases": [{"version": "1.0.0", "download_url": "https://example.com/p"}],
                }
            ]
        })
        assert "sync-1" in catalog._plugins
        assert catalog._ratings["sync-1"] == 4.0
        assert len(catalog._releases["sync-1"]) == 1


class TestPluginManager:
    def setup_method(self) -> None:
        self.tmp_dir = Path(__file__).parent / "_test_plugins"
        self.tmp_dir.mkdir(exist_ok=True)
        self.manager = PluginManager(plugins_dir=self.tmp_dir)

    def teardown_method(self) -> None:
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @pytest.mark.asyncio
    async def test_install_plugin_simulated(self) -> None:
        installed = await self.manager.install_plugin("https://example.com/my-plugin", source="local")
        assert installed.metadata.name == "my-plugin"
        assert installed.status == InstallationStatus.INSTALLED
        assert installed.install_path.exists()

    @pytest.mark.asyncio
    async def test_install_plugin_already_installed(self) -> None:
        await self.manager.install_plugin("https://example.com/dup-plugin", source="local")
        with pytest.raises(ValueError, match="already installed"):
            await self.manager.install_plugin("https://example.com/dup-plugin", source="local")

    @pytest.mark.asyncio
    async def test_uninstall_plugin(self) -> None:
        installed = await self.manager.install_plugin("https://example.com/to-uninstall", source="local")
        assert installed.metadata.id in self.manager._installed
        result = await self.manager.uninstall_plugin(installed.metadata.id)
        assert result is True
        assert installed.metadata.id not in self.manager._installed

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self) -> None:
        result = await self.manager.uninstall_plugin("nonexistent-plugin")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_installed(self) -> None:
        await self.manager.install_plugin("https://example.com/plugin-a", source="local")
        await self.manager.install_plugin("https://example.com/plugin-b", source="local")
        plugins = self.manager.list_installed()
        assert len(plugins) == 2
        names = {p.metadata.name for p in plugins}
        assert "plugin-a" in names
        assert "plugin-b" in names

    @pytest.mark.asyncio
    async def test_install_then_list_contains_installed_plugin(self) -> None:
        installed = await self.manager.install_plugin("https://example.com/list-check", source="local")
        assert installed in self.manager.list_installed()

    @pytest.mark.asyncio
    async def test_search_plugins_local(self) -> None:
        await self.manager.install_plugin("https://example.com/search-me", source="local")
        results = self.manager.search_plugins("search")
        assert len(results) >= 1
        assert any("search" in p.name for p in results)

    def test_search_plugins_remote(self) -> None:
        self.manager._catalog._plugins = {
            "remote-1": PluginMetadata(id="remote-1", name="remote-tool", version="1.0.0", description="A remote tool"),
        }
        results = self.manager.search_plugins("remote")
        assert len(results) >= 1

    def test_get_plugin_info_installed(self) -> None:
        meta = PluginMetadata(id="info-test", name="info-plugin", version="1.0.0")
        self.manager._installed["info-test"] = InstalledPlugin(
            metadata=meta,
            install_path=self.tmp_dir / "info-test",
            status=InstallationStatus.INSTALLED,
        )
        result = self.manager.get_plugin_info("info-test")
        assert result is not None
        assert result.name == "info-plugin"

    def test_get_plugin_info_from_catalog(self) -> None:
        self.manager._catalog._plugins = {
            "cat-1": PluginMetadata(id="cat-1", name="catalog-plugin", version="0.5.0"),
        }
        result = self.manager.get_plugin_info("cat-1")
        assert result is not None
        assert result.name == "catalog-plugin"

    def test_get_plugin_info_not_found(self) -> None:
        assert self.manager.get_plugin_info("does-not-exist") is None

    def test_get_installation_status(self) -> None:
        assert self.manager.get_installation_status("missing") == InstallationStatus.NOT_INSTALLED

    @pytest.mark.asyncio
    async def test_update_plugin_not_installed(self) -> None:
        with pytest.raises(ValueError, match="not installed"):
            await self.manager.update_plugin("not-installed")

    @pytest.mark.asyncio
    async def test_persistence_across_reload(self) -> None:
        await self.manager.install_plugin("https://example.com/persist-me", source="local")
        manager2 = PluginManager(plugins_dir=self.tmp_dir)
        assert "persist-me" in manager2._installed
