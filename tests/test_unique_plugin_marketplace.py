from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

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
        result = self.manager.uninstall_plugin(installed.metadata.id)
        assert result is True
        assert installed.metadata.id not in self.manager._installed

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self) -> None:
        result = self.manager.uninstall_plugin("nonexistent-plugin")
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

    @pytest.mark.asyncio
    async def test_install_traversal_paths_stay_inside_plugins_dir(self) -> None:
        root = self.tmp_dir.resolve()
        for bad in ("https://evil.com/..", "C:\\Windows", "https://x.com/..\\..\\etc", ".."):
            installed = await self.manager.install_plugin(bad, source="local")
            path = installed.install_path.resolve()
            assert path == root or path.is_relative_to(root)
            assert path.name not in (".", "..")
            assert (path / "plugin.json").exists()

    def test_name_from_url_sanitizes(self) -> None:
        assert self.manager._name_from_url("https://github.com/acme/my-plugin.git") == "my-plugin"
        assert self.manager._name_from_url("https://evil.com/..").startswith("plugin_")
        assert self.manager._name_from_url("https://x.com/..\\..\\etc") == "etc"
        assert self.manager._name_from_url("https://x.com/...") != ""


# ---------------------------------------------------------------------------
# Fakes for network / subprocess / catalog interactions
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload: Any = None, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self._payload is None:
            raise RuntimeError("boom")

    def json(self) -> Any:
        return self._payload


def _fake_httpx(monkeypatch: pytest.MonkeyPatch, response: Any = None, raises: BaseException | None = None) -> None:
    import httpx

    class _Client:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: object) -> bool:
            return False

        async def get(self, _url: str) -> Any:
            if raises is not None:
                raise raises
            return response

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


class _StubCatalog:
    def __init__(self, releases: list[PluginRelease] | None = None) -> None:
        self._releases = releases or []
        self.sync_calls = 0

    async def sync(self) -> bool:
        self.sync_calls += 1
        return True

    def get_releases(self, _pid: str) -> list[PluginRelease]:
        return self._releases


class TestPluginCatalogSync:
    def _catalog(self, tmp_path: Path, url: str = "") -> PluginCatalog:
        return PluginCatalog(catalog_url=url, cache_dir=tmp_path / "cache")

    async def test_sync_no_url_uses_local_cache(self, tmp_path: Path) -> None:
        catalog = self._catalog(tmp_path)
        assert await catalog.sync() is False

    async def test_sync_success_parses_and_caches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: None)
        payload = {"plugins": [{"id": "p1", "name": "alpha", "version": "1.0.0", "category": "coding"}]}
        _fake_httpx(monkeypatch, response=_Resp(payload))
        catalog = self._catalog(tmp_path, url="https://example.com/catalog.json")
        assert await catalog.sync() is True
        assert "p1" in catalog._plugins
        assert (tmp_path / "cache" / "catalog.json").exists()

    async def test_sync_blocked_by_ssrf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: "private")
        catalog = self._catalog(tmp_path, url="http://169.254.1.1/catalog.json")
        assert await catalog.sync() is False

    async def test_sync_exception_falls_back_to_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: None)
        _fake_httpx(monkeypatch, raises=RuntimeError("network down"))
        catalog = self._catalog(tmp_path, url="https://example.com/catalog.json")
        assert await catalog.sync() is False

    async def test_load_local_cache_success(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "catalog.json").write_text(
            json.dumps({"plugins": [{"id": "p9", "name": "cached", "version": "1.0.0"}]})
        )
        catalog = self._catalog(tmp_path)
        assert await catalog.sync() is True
        assert "p9" in catalog._plugins

    async def test_load_local_cache_malformed(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "catalog.json").write_text("not json {")
        catalog = self._catalog(tmp_path)
        assert await catalog.sync() is False

    def test_save_local_cache_serialization_error(self, tmp_path: Path) -> None:
        catalog = self._catalog(tmp_path)
        catalog._save_local_cache({"bad": object()})  # unserializable -> swallowed
        assert not (tmp_path / "cache" / "catalog.json").exists()


class TestCatalogSearchDescription:
    def test_search_matches_description(self, tmp_path: Path) -> None:
        catalog = PluginCatalog(cache_dir=tmp_path)
        catalog._plugins = {
            "x": PluginMetadata(id="x", name="zzz", version="1.0", description="a scraper tool"),
        }
        assert catalog.search("scraper") == [catalog._plugins["x"]]


class TestPluginManagerPaths:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> PluginManager:
        return PluginManager(plugins_dir=tmp_path / "plugins")

    def test_catalog_property(self, manager: PluginManager) -> None:
        assert isinstance(manager.catalog, PluginCatalog)

    def test_get_installation_status_installed(self, manager: PluginManager) -> None:
        meta = PluginMetadata(id="m", name="m", version="1.0.0")
        manager._installed["m"] = InstalledPlugin(metadata=meta, install_path=manager._plugins_dir / "m")
        assert manager.get_installation_status("m") == InstallationStatus.INSTALLED

    async def test_install_rejects_escaping_name(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(manager, "_name_from_url", lambda _u: "../escape")
        with pytest.raises(ValueError, match="Invalid plugin name"):
            await manager.install_plugin("https://x/y", source="local")

    async def test_install_remote_source(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import AsyncMock

        monkeypatch.setattr(manager, "_fetch_remote_metadata", AsyncMock(return_value=None))
        installed = await manager.install_plugin("https://x.com/rem", source="remote")
        assert installed.metadata.name == "rem"

    async def test_install_real_when_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        manager = PluginManager(plugins_dir=tmp_path / "plugins", allow_real_install=True)
        monkeypatch.setattr(manager, "_real_install", AsyncMock())
        installed = await manager.install_plugin("https://x.com/real", source="local")
        assert installed.metadata.name == "real"

    async def test_install_wraps_and_raises_errors(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import AsyncMock

        monkeypatch.setattr(manager, "_simulated_install", AsyncMock(side_effect=OSError("disk full")))
        with pytest.raises(OSError):
            await manager.install_plugin("https://x.com/fail", source="local")

    async def test_uninstall_swallows_rmtree_error(self, manager: PluginManager) -> None:
        # install_path is a FILE -> shutil.rmtree raises, uninstall still returns True
        target = manager._plugins_dir / "as-file"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        meta = PluginMetadata(id="f", name="f", version="1.0.0")
        manager._installed["f"] = InstalledPlugin(metadata=meta, install_path=target)
        assert manager.uninstall_plugin("f") is True

    def test_load_registry_malformed(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "registry.json").write_text("{ broken")
        manager = PluginManager(plugins_dir=plugins_dir)  # must not raise
        assert manager._installed == {}

    def test_save_registry_swallows_error(self, manager: PluginManager, tmp_path: Path) -> None:
        # point registry at a directory so write_text fails
        manager._registry_file = tmp_path
        meta = PluginMetadata(id="m", name="m", version="1.0.0")
        manager._installed["m"] = InstalledPlugin(metadata=meta, install_path=manager._plugins_dir / "m")
        manager._save_registry()  # must not raise


class TestUpdatePlugin:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> PluginManager:
        return PluginManager(plugins_dir=tmp_path / "plugins")

    def _install(self, manager: PluginManager, name: str, version: str) -> InstalledPlugin:
        meta = PluginMetadata(id=name, name=name, version=version)
        inst = InstalledPlugin(
            metadata=meta,
            install_path=manager._plugins_dir / name,
            status=InstallationStatus.INSTALLED,
        )
        manager._installed[name] = inst
        return inst

    async def test_update_no_releases(self, manager: PluginManager) -> None:
        manager._catalog = cast(PluginCatalog, _StubCatalog([]))
        self._install(manager, "up", "1.0.0")
        result = await manager.update_plugin("up")
        assert result.metadata.version == "1.0.0"

    async def test_update_already_latest(self, manager: PluginManager) -> None:
        manager._catalog = cast(PluginCatalog, _StubCatalog([PluginRelease(version="1.0.0")]))
        self._install(manager, "up", "1.0.0")
        result = await manager.update_plugin("up")
        assert result.metadata.version == "1.0.0"

    async def test_update_success(self, manager: PluginManager) -> None:
        manager._catalog = cast(PluginCatalog, _StubCatalog([PluginRelease(version="2.0.0")]))
        self._install(manager, "up", "1.0.0")
        result = await manager.update_plugin("up")
        assert result.metadata.version == "2.0.0"
        assert result.status == InstallationStatus.INSTALLED

    async def test_update_real_install_when_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import AsyncMock

        manager = PluginManager(plugins_dir=tmp_path / "plugins", allow_real_install=True)
        manager._catalog = cast(PluginCatalog, _StubCatalog([PluginRelease(version="2.0.0", download_url="https://x/p")]))
        self._install(manager, "up", "1.0.0")
        monkeypatch.setattr(manager, "_real_install", AsyncMock())
        result = await manager.update_plugin("up")
        assert result.metadata.version == "2.0.0"

    async def test_update_failure_marks_failed(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import AsyncMock

        manager._catalog = cast(PluginCatalog, _StubCatalog([PluginRelease(version="2.0.0")]))
        inst = self._install(manager, "up", "1.0.0")
        monkeypatch.setattr(manager, "_simulated_install", AsyncMock(side_effect=OSError("nope")))
        with pytest.raises(OSError):
            await manager.update_plugin("up")
        assert inst.status == InstallationStatus.FAILED


class TestRealInstall:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> PluginManager:
        return PluginManager(plugins_dir=tmp_path / "plugins", allow_real_install=True)

    async def test_real_install_no_deps(self, manager: PluginManager) -> None:
        meta = PluginMetadata(id="d", name="d", version="1.0.0")
        await manager._real_install("https://x/d", manager._plugins_dir / "d", meta)
        assert (manager._plugins_dir / "d" / "plugin.json").exists()

    async def test_real_install_deps_ok(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        class _Proc:
            returncode = 0

            async def wait(self) -> int:
                return 0

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        meta = PluginMetadata(id="d", name="d", version="1.0", dependencies=["requests"])
        await manager._real_install("https://x/d", manager._plugins_dir / "d", meta)
        assert (manager._plugins_dir / "d" / "plugin.json").exists()

    async def test_real_install_deps_nonzero(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        class _Proc:
            returncode = 1

            async def wait(self) -> int:
                return 1

        async def fake_exec(*_a: object, **_k: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        meta = PluginMetadata(id="d", name="d", version="1.0", dependencies=["nope"])
        await manager._real_install("https://x/d", manager._plugins_dir / "d", meta)

    async def test_real_install_pip_missing(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        async def fake_exec(*_a: object, **_k: object) -> None:
            raise FileNotFoundError("pip")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        meta = PluginMetadata(id="d", name="d", version="1.0", dependencies=["x"])
        await manager._real_install("https://x/d", manager._plugins_dir / "d", meta)

    async def test_real_install_deps_generic_error(
        self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        async def fake_exec(*_a: object, **_k: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        meta = PluginMetadata(id="d", name="d", version="1.0", dependencies=["x"])
        await manager._real_install("https://x/d", manager._plugins_dir / "d", meta)


class TestFetchRemoteMetadata:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> PluginManager:
        return PluginManager(plugins_dir=tmp_path / "plugins")

    async def test_blocked_by_ssrf(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: "private")
        assert await manager._fetch_remote_metadata("http://10.0.0.1/p") is None

    async def test_success_200(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: None)
        payload = {"id": "rm", "name": "remote-meta", "version": "3.1.0", "category": "voice"}
        _fake_httpx(monkeypatch, response=_Resp(payload))
        meta = await manager._fetch_remote_metadata("https://x.com/plugin")
        assert meta is not None
        assert meta.name == "remote-meta"
        assert meta.category == Category.VOICE

    async def test_non_200_returns_none(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: None)
        _fake_httpx(monkeypatch, response=_Resp(None, status=404))
        assert await manager._fetch_remote_metadata("https://x.com/plugin") is None

    async def test_exception_returns_none(self, manager: PluginManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda _u: None)
        _fake_httpx(monkeypatch, raises=RuntimeError("down"))
        assert await manager._fetch_remote_metadata("https://x.com/plugin") is None


class TestReadLocalMetadata:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> PluginManager:
        return PluginManager(plugins_dir=tmp_path / "plugins")

    def test_reads_plugin_json_in_dir(self, manager: PluginManager) -> None:
        plugin_dir = manager._plugins_dir / "loc"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": "local-meta", "version": "2.0.0"}))
        meta = manager._read_local_metadata(str(plugin_dir))
        assert meta is not None
        assert meta.name == "local-meta"

    def test_missing_plugin_json_returns_none(self, manager: PluginManager) -> None:
        plugin_dir = manager._plugins_dir / "empty"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        assert manager._read_local_metadata(str(plugin_dir)) is None

    def test_malformed_plugin_json_returns_none(self, manager: PluginManager) -> None:
        plugin_dir = manager._plugins_dir / "bad"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "plugin.json").write_text("nonsense {{")
        assert manager._read_local_metadata(str(plugin_dir)) is None

    def test_sibling_prefix_rejected(self, manager: PluginManager) -> None:
        sibling = Path(str(manager._plugins_dir) + "_evil")
        assert manager._read_local_metadata(str(sibling)) is None
