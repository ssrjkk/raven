from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class Category(Enum):
    CODING = "coding"
    AUTOMATION = "automation"
    UNIQUE = "unique"
    VOICE = "voice"
    CHANNEL = "channel"


class InstallationStatus(Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    UPDATE_AVAILABLE = "update_available"


@dataclass
class PluginMetadata:
    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    icon: str = ""
    category: Category = Category.UNIQUE


@dataclass
class PluginRelease:
    version: str
    download_url: str = ""
    checksum: str = ""
    min_raven_version: str = ""
    requires: list[str] = field(default_factory=list)
    released_at: str = ""


@dataclass
class InstalledPlugin:
    metadata: PluginMetadata
    install_path: Path
    installed_at: str = ""
    status: InstallationStatus = InstallationStatus.INSTALLED


class PluginCatalog:
    def __init__(self, catalog_url: str = "", cache_dir: Path | None = None) -> None:
        self.catalog_url = catalog_url
        self._cache_dir = cache_dir or Path.home() / ".raven" / "catalog"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._plugins: dict[str, PluginMetadata] = {}
        self._releases: dict[str, list[PluginRelease]] = {}
        self._ratings: dict[str, float] = {}
        self._downloads: dict[str, int] = {}
        self._synced: bool = False

    def search(self, query: str) -> list[PluginMetadata]:
        query_lower = query.lower()
        results: list[PluginMetadata] = []
        for plugin in self._plugins.values():
            if query_lower in plugin.name.lower():
                results.append(plugin)
                continue
            if query_lower in plugin.description.lower():
                results.append(plugin)
                continue
            if any(query_lower == t.lower() for t in plugin.tags):
                results.append(plugin)
                continue
            if query_lower == plugin.category.value:
                results.append(plugin)
                continue
        return results

    async def sync(self) -> bool:
        if not self.catalog_url:
            logger.debug("[catalog] no catalog_url configured, using local cache")
            return self._load_local_cache()

        try:
            import httpx

            from raven.core.security.ssrf import validate_url

            if validate_url(self.catalog_url):
                logger.warning("[catalog] catalog URL blocked by SSRF guard: {}", self.catalog_url)
                return self._load_local_cache()

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.catalog_url)
                resp.raise_for_status()
                data = resp.json()
            self._parse_catalog(data)
            self._synced = True
            self._save_local_cache(data)
            logger.info("[catalog] synced {} plugins from {}", len(self._plugins), self.catalog_url)
            return True
        except Exception as exc:
            logger.warning("[catalog] sync failed ({}), falling back to local cache", exc)
            return self._load_local_cache()

    def get_top_rated(self, limit: int = 10) -> list[tuple[PluginMetadata, float]]:
        scored = [(self._plugins[pid], self._ratings.get(pid, 0.0)) for pid in self._plugins if pid in self._ratings]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def get_most_downloaded(self, limit: int = 10) -> list[tuple[PluginMetadata, int]]:
        scored = [(self._plugins[pid], self._downloads.get(pid, 0)) for pid in self._plugins if pid in self._downloads]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def get_releases(self, plugin_id: str) -> list[PluginRelease]:
        return self._releases.get(plugin_id, [])

    def add_local_plugin(self, metadata: PluginMetadata) -> None:
        self._plugins[metadata.id] = metadata

    def _parse_catalog(self, data: dict[str, Any]) -> None:
        self._plugins.clear()
        self._releases.clear()
        self._ratings.clear()
        self._downloads.clear()
        for entry in data.get("plugins", []):
            metadata = PluginMetadata(
                id=entry.get("id", str(uuid.uuid4())),
                name=entry.get("name", "unknown"),
                version=entry.get("version", "0.0.0"),
                description=entry.get("description", ""),
                author=entry.get("author", ""),
                tags=entry.get("tags", []),
                dependencies=entry.get("dependencies", []),
                icon=entry.get("icon", ""),
                category=Category(entry.get("category", "unique")),
            )
            self._plugins[metadata.id] = metadata
            self._ratings[metadata.id] = entry.get("rating", 0.0)
            self._downloads[metadata.id] = entry.get("downloads", 0)
            releases_data = entry.get("releases", [])
            self._releases[metadata.id] = [
                PluginRelease(
                    version=r.get("version", "0.0.0"),
                    download_url=r.get("download_url", ""),
                    checksum=r.get("checksum", ""),
                    min_raven_version=r.get("min_raven_version", ""),
                    requires=r.get("requires", []),
                    released_at=r.get("released_at", ""),
                )
                for r in releases_data
            ]

    def _save_local_cache(self, data: dict[str, Any]) -> None:
        cache_file = self._cache_dir / "catalog.json"
        try:
            cache_file.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("[catalog] failed to save cache: {}", exc)

    def _load_local_cache(self) -> bool:
        cache_file = self._cache_dir / "catalog.json"
        if not cache_file.exists():
            logger.debug("[catalog] no local cache found")
            return False
        try:
            data = json.loads(cache_file.read_text())
            self._parse_catalog(data)
            self._synced = True
            logger.info("[catalog] loaded {} plugins from local cache", len(self._plugins))
            return True
        except Exception as exc:
            logger.warning("[catalog] failed to load local cache: {}", exc)
            return False


class PluginManager:
    def __init__(
        self, plugins_dir: Path | None = None, catalog: PluginCatalog | None = None, allow_real_install: bool = False
    ) -> None:
        self._plugins_dir = plugins_dir or Path.home() / ".raven" / "plugins"
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        self._registry_file = self._plugins_dir / "registry.json"
        self._catalog = catalog or PluginCatalog()
        self._allow_real_install = allow_real_install
        self._installed: dict[str, InstalledPlugin] = {}
        self._load_registry()

    @property
    def catalog(self) -> PluginCatalog:
        return self._catalog

    async def install_plugin(self, url_or_path: str, source: str = "remote") -> InstalledPlugin:
        plugin_id = self._name_from_url(url_or_path)
        if plugin_id in self._installed:
            msg = f"Plugin '{plugin_id}' is already installed"
            raise ValueError(msg)

        metadata = PluginMetadata(
            id=plugin_id,
            name=plugin_id,
            version="0.0.0",
            description="",
            author="",
        )

        install_path = self._plugins_dir / plugin_id
        install_root = self._plugins_dir.resolve()
        install_path = install_path.resolve()
        if not (install_path == install_root or install_path.is_relative_to(install_root)):
            msg = f"Invalid plugin name: {plugin_id}"
            raise ValueError(msg)

        try:
            if source == "remote":
                metadata = await self._fetch_remote_metadata(url_or_path) or metadata
            elif source == "local":
                metadata = self._read_local_metadata(url_or_path) or metadata

            if self._allow_real_install:
                await self._real_install(url_or_path, install_path, metadata)
            else:
                await self._simulated_install(install_path, metadata)

            installed = InstalledPlugin(
                metadata=metadata,
                install_path=install_path,
                installed_at=datetime.now(UTC).isoformat(),
                status=InstallationStatus.INSTALLED,
            )
            self._installed[metadata.id] = installed
            self._save_registry()
            logger.info("[plugin] installed '{}' v{} from {}", metadata.name, metadata.version, url_or_path)
            return installed
        except Exception as exc:
            logger.error("[plugin] failed to install '{}': {}", plugin_id, exc)
            raise

    def uninstall_plugin(self, name: str) -> bool:
        installed = self._installed.pop(name, None)
        if installed is None:
            logger.warning("[plugin] '{}' not installed", name)
            return False

        try:
            if installed.install_path.exists():
                import shutil

                shutil.rmtree(installed.install_path)
        except Exception as exc:
            logger.warning("[plugin] failed to remove files for '{}': {}", name, exc)

        self._save_registry()
        logger.info("[plugin] uninstalled '{}'", name)
        return True

    async def update_plugin(self, name: str) -> InstalledPlugin:
        installed = self._installed.get(name)
        if installed is None:
            msg = f"Plugin '{name}' is not installed"
            raise ValueError(msg)

        await self._catalog.sync()
        releases = self._catalog.get_releases(installed.metadata.id)
        if not releases:
            logger.info("[plugin] no updates found for '{}'", name)
            return installed

        latest = max(releases, key=lambda r: r.version)
        if latest.version <= installed.metadata.version:
            logger.info("[plugin] '{}' is already at latest version {}", name, installed.metadata.version)
            return installed

        install_path = installed.install_path
        try:
            if self._allow_real_install and latest.download_url:
                await self._real_install(latest.download_url, install_path, installed.metadata)
            else:
                await self._simulated_install(install_path, installed.metadata)

            installed.metadata.version = latest.version
            installed.status = InstallationStatus.INSTALLED
            installed.installed_at = datetime.now(UTC).isoformat()
            self._save_registry()
            logger.info("[plugin] updated '{}' to v{}", name, latest.version)
        except Exception as exc:
            installed.status = InstallationStatus.FAILED
            logger.error("[plugin] update failed for '{}': {}", name, exc)
            raise

        return installed

    def list_installed(self) -> list[InstalledPlugin]:
        return list(self._installed.values())

    def search_plugins(self, query: str) -> list[PluginMetadata]:
        local_results: list[PluginMetadata] = []
        for installed in self._installed.values():
            if (
                query.lower() in installed.metadata.name.lower()
                or query.lower() in installed.metadata.description.lower()
            ):
                local_results.append(installed.metadata)
        remote_results = self._catalog.search(query)
        seen = {p.id for p in local_results}
        local_results.extend(p for p in remote_results if p.id not in seen)
        return local_results

    def get_plugin_info(self, name: str) -> PluginMetadata | None:
        installed = self._installed.get(name)
        if installed:
            return installed.metadata
        for pid, plugin in self._catalog._plugins.items():
            if plugin.name == name or pid == name:
                return plugin
        return None

    def get_installation_status(self, name: str) -> InstallationStatus:
        installed = self._installed.get(name)
        if installed is None:
            return InstallationStatus.NOT_INSTALLED
        return installed.status

    def _load_registry(self) -> None:
        if not self._registry_file.exists():
            return
        try:
            data = json.loads(self._registry_file.read_text())
            for entry in data.get("installed", []):
                meta = PluginMetadata(**entry["metadata"])
                install_path = Path(entry["install_path"])
                installed = InstalledPlugin(
                    metadata=meta,
                    install_path=install_path,
                    installed_at=entry.get("installed_at", ""),
                    status=InstallationStatus(entry.get("status", "installed")),
                )
                self._installed[meta.id] = installed
        except Exception as exc:
            logger.warning("[plugin] failed to load registry: {}", exc)

    def _save_registry(self) -> None:
        data = {
            "installed": [
                {
                    "metadata": {
                        "id": p.metadata.id,
                        "name": p.metadata.name,
                        "version": p.metadata.version,
                        "description": p.metadata.description,
                        "author": p.metadata.author,
                        "tags": p.metadata.tags,
                        "dependencies": p.metadata.dependencies,
                        "icon": p.metadata.icon,
                        "category": p.metadata.category.value,
                    },
                    "install_path": str(p.install_path),
                    "installed_at": p.installed_at,
                    "status": p.status.value,
                }
                for p in self._installed.values()
            ]
        }
        try:
            self._registry_file.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("[plugin] failed to save registry: {}", exc)

    def _name_from_url(self, url_or_path: str) -> str:
        raw = url_or_path.rstrip("/\\")
        name = raw.split("/")[-1].split("\\")[-1]
        name = name.removesuffix(".git").removesuffix(".zip").removesuffix(".tar.gz")
        name = name.rstrip(". ")
        if not name:
            name = f"plugin_{uuid.uuid4().hex[:8]}"
        return name

    async def _fetch_remote_metadata(self, url: str) -> PluginMetadata | None:
        try:
            import httpx

            from raven.core.security.ssrf import validate_url

            if validate_url(url):
                logger.debug("[plugin] remote metadata URL blocked by SSRF guard: {}", url)
                return None

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url.rstrip('/')}/plugin.json")
                if resp.status_code == 200:
                    data = resp.json()
                    return PluginMetadata(
                        id=data.get("id", self._name_from_url(url)),
                        name=data.get("name", self._name_from_url(url)),
                        version=data.get("version", "0.0.0"),
                        description=data.get("description", ""),
                        author=data.get("author", ""),
                        tags=data.get("tags", []),
                        dependencies=data.get("dependencies", []),
                        icon=data.get("icon", ""),
                        category=Category(data.get("category", "unique")),
                    )
        except Exception as exc:
            logger.debug("[plugin] could not fetch remote metadata from {}: {}", url, exc)
        return None

    def _read_local_metadata(self, path: str | Path) -> PluginMetadata | None:
        base = os.path.abspath(str(self._plugins_dir))  # noqa: PTH100
        resolved = os.path.abspath(os.path.normpath(os.path.expanduser(str(path))))  # noqa: PTH100, PTH111
        if not resolved.startswith(base):
            return None
        if resolved != base and not resolved.startswith(base + os.sep):
            return None
        path = Path(resolved)
        plugin_json = path / "plugin.json" if path.is_dir() else path.parent / "plugin.json"
        if plugin_json.exists():
            try:
                data = json.loads(plugin_json.read_text())
                return PluginMetadata(
                    id=data.get("id", path.name),
                    name=data.get("name", path.name),
                    version=data.get("version", "0.0.0"),
                    description=data.get("description", ""),
                    author=data.get("author", ""),
                    tags=data.get("tags", []),
                    dependencies=data.get("dependencies", []),
                    icon=data.get("icon", ""),
                    category=Category(data.get("category", "unique")),
                )
            except Exception as exc:
                logger.debug("[plugin] could not read local metadata: {}", exc)
        return None

    async def _real_install(self, url_or_path: str, install_path: Path, metadata: PluginMetadata) -> None:
        install_path.mkdir(parents=True, exist_ok=True)
        plugin_json = install_path / "plugin.json"
        plugin_json.write_text(
            json.dumps(
                {
                    "id": metadata.id,
                    "name": metadata.name,
                    "version": metadata.version,
                    "description": metadata.description,
                    "author": metadata.author,
                    "tags": metadata.tags,
                    "dependencies": metadata.dependencies,
                    "icon": metadata.icon,
                    "category": metadata.category.value,
                },
                indent=2,
            )
        )

        if metadata.dependencies:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pip",
                    "install",
                    *metadata.dependencies,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                if proc.returncode != 0:
                    logger.warning(
                        "[plugin] pip install for deps of '{}' exited with {}", metadata.name, proc.returncode
                    )
            except FileNotFoundError:
                logger.debug("[plugin] pip not available, skipping dependency install")
            except Exception as exc:
                logger.warning("[plugin] pip install failed for '{}': {}", metadata.name, exc)

    async def _simulated_install(self, install_path: Path, metadata: PluginMetadata) -> None:
        await asyncio.sleep(0.05)
        install_path.mkdir(parents=True, exist_ok=True)
        plugin_json = install_path / "plugin.json"
        plugin_json.write_text(
            json.dumps(
                {
                    "id": metadata.id,
                    "name": metadata.name,
                    "version": metadata.version,
                    "description": metadata.description,
                    "author": metadata.author,
                    "tags": metadata.tags,
                    "dependencies": metadata.dependencies,
                    "icon": metadata.icon,
                    "category": metadata.category.value,
                },
                indent=2,
            )
        )
        (install_path / "plugin.py").write_text(
            f"# {metadata.name} v{metadata.version}\n# Auto-generated by Raven Plugin Marketplace\n"
        )
