from __future__ import annotations

import asyncio
import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.security.ssrf import safe_fetch_async, validate_url_async
from raven.plugins.manifest import PluginManifest, _version_ge

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_FILES_PER_ARCHIVE = 500
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


@dataclass
class CatalogEntry:
    """A plugin version advertised by a registry/catalog."""

    name: str
    version: str
    description: str = ""
    source: Path | None = None
    url: str | None = None


def read_installed_version(plugin_dir: Path) -> str | None:
    """Return the installed plugin version, or None when the dir is not a plugin."""
    if not (plugin_dir / "plugin.py").exists():
        return None
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.exists():
        manifest = PluginManifest.from_file(manifest_path)
        if manifest is not None:
            return manifest.version
    return "0.0.0"


class PluginRegistry:
    """Catalog of installable plugins.

    ``source`` is either a local directory (each subdir is a plugin) or an
    ``http(s)`` base URL serving ``index.json`` with entries:
    ``{"plugins": [{"name": ..., "version": ..., "url": "…/bundle.zip"}]}``.
    Remote fetches are SSRF-protected on every request/redirect.
    """

    def __init__(self, source: str | Path) -> None:
        raw = str(source)
        if raw.startswith(("http://", "https://")):
            self._source: str | Path = raw
        else:
            self._source = Path(raw)

    def _is_remote(self) -> bool:
        return isinstance(self._source, str)

    def _list_local(self) -> list[CatalogEntry]:
        src = self._source
        if not isinstance(src, Path) or not src.is_dir():
            logger.warning("Plugin registry directory not found: {}", src)
            return []
        entries: list[CatalogEntry] = []
        for child in sorted(src.iterdir()):
            if not child.is_dir() or child.name == "__pycache__":
                continue
            if not (child / "plugin.py").exists():
                continue
            version = read_installed_version(child) or "0.0.0"
            description = ""
            manifest_path = child / "manifest.json"
            if manifest_path.exists():
                manifest = PluginManifest.from_file(manifest_path)
                if manifest is not None:
                    description = manifest.description
            entries.append(
                CatalogEntry(
                    name=child.name,
                    version=version,
                    description=description,
                    source=child,
                )
            )
        return entries

    async def list_available(self) -> list[CatalogEntry]:
        if self._is_remote():
            return await self._list_remote()
        return self._list_local()

    async def _list_remote(self) -> list[CatalogEntry]:
        source = self._source
        if not isinstance(source, str):
            return []
        url = f"{source.rstrip('/')}/index.json"
        resp = await safe_fetch_async(url, max_bytes=1_000_000)
        if resp.status_code != 200:
            raise RuntimeError(f"Plugin catalog fetch failed: HTTP {resp.status_code}")
        data: Any = resp.json()
        return await _parse_catalog(data)

    async def install(self, name: str, dest_dir: Path, force: bool = False) -> bool:
        """Install or update a single plugin. Returns True when installed."""
        if not _SAFE_NAME.match(name):
            raise ValueError(f"Unsafe plugin name: {name!r}")
        entries = await self.list_available()
        entry = next((e for e in entries if e.name == name), None)
        if entry is None:
            logger.info("Plugin {} not present in registry", name)
            return False
        installed = await asyncio.to_thread(read_installed_version, dest_dir / name)
        if not force and installed is not None and _version_ge(installed, entry.version):
            logger.info("Plugin {} already at or newer than catalog ({} >= {})", name, installed, entry.version)
            return True

        content: bytes | None = None
        if entry.source is None and entry.url is not None:
            resp = await safe_fetch_async(entry.url, max_bytes=_MAX_ARCHIVE_BYTES)
            if resp.status_code != 200:
                raise RuntimeError(f"Plugin download failed: HTTP {resp.status_code}")
            content = resp.content

        def _stage() -> None:
            dest_dir.mkdir(parents=True, exist_ok=True)
            tmp = dest_dir / f".{name}.tmp"
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            try:
                if entry.source is not None:
                    _copy_plugin_dir(entry.source, tmp)
                elif content is not None:
                    _extract_zip(content, tmp)
                else:
                    raise RuntimeError(f"Plugin {name} has no installable source")
                _normalize_plugin_root(tmp)
                if read_installed_version(tmp) is None:
                    raise RuntimeError(f"Plugin {name} bundle contains no valid plugin.py/manifest.json")
                target = dest_dir / name
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                tmp.rename(target)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise

        await asyncio.to_thread(_stage)
        logger.info("Plugin {} updated to v{}", name, entry.version)
        return True

    async def update(
        self, dest_dir: Path, names: list[str] | None = None, force: bool = False
    ) -> dict[str, bool]:
        """Update all catalog plugins (or a subset). Returns {name: installed}."""
        entries = await self.list_available()
        result: dict[str, bool] = {}
        for entry in entries:
            if names and entry.name not in names:
                continue
            result[entry.name] = await self.install(entry.name, dest_dir, force=force)
        return result


async def _parse_catalog(data: Any) -> list[CatalogEntry]:
    """Parse the catalog payload into entries, dropping unsafe/private entries."""
    plugins = data.get("plugins", []) if isinstance(data, dict) else []
    if not isinstance(plugins, list):
        return []
    entries: list[CatalogEntry] = []
    for item in plugins:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        version = str(item.get("version", "0.0.0"))
        url = str(item.get("url", ""))
        if not _SAFE_NAME.match(name):
            logger.warning("Catalog entry with unsafe name skipped: {}", name)
            continue
        if url and not url.startswith(("http://", "https://")):
            logger.warning("Catalog entry {} has invalid archive url", name)
            continue
        if url:
            error = await validate_url_async(url)
            if error:
                logger.warning("Catalog entry {} archive blocked: {}", name, error)
                continue
        entries.append(
            CatalogEntry(
                name=name,
                version=version,
                description=str(item.get("description", "")),
                url=url or None,
            )
        )
    return entries


def _copy_plugin_dir(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _extract_zip(content: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        members = zf.infolist()
        if len(members) > _MAX_FILES_PER_ARCHIVE:
            raise RuntimeError(f"Plugin archive exceeds {_MAX_FILES_PER_ARCHIVE} files")
        for member in members:
            target = _safe_join(dest, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _safe_join(root: Path, name: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / name).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"Path traversal blocked in archive entry: {name!r}")
    return candidate


def _normalize_plugin_root(dest: Path) -> None:
    """Flatten a single top-level directory produced by an archive wrapper."""
    if (dest / "plugin.py").exists():
        return
    subdirs = [
        d
        for d in dest.iterdir()
        if d.is_dir() and ((d / "plugin.py").exists() or (d / "manifest.json").exists())
    ]
    if len(subdirs) == 1:
        inner = subdirs[0]
        for item in inner.iterdir():
            item.rename(dest / item.name)
        inner.rmdir()
