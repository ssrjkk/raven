from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from raven.plugins.registry import (
    PluginRegistry,
    _extract_zip,
    _normalize_plugin_root,
    _parse_catalog,
    _safe_join,
    read_installed_version,
)

_PLUGIN_PY = 'async def hello() -> str:\n    return "hi"\n'
_MANIFEST = '{"name":"foo","version":"1.0.0","description":"Foo plugin"}'


def _write_plugin(root: Path, name: str, version: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.py").write_text(_PLUGIN_PY, encoding="utf-8")
    (d / "manifest.json").write_text(
        f'{{"name":"{name}","version":"{version}"}}', encoding="utf-8"
    )


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir()
    _write_plugin(root, "foo", "1.0.0")
    _write_plugin(root, "bar", "0.5.0")
    return root


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plugins"
    d.mkdir()
    _write_plugin(d, "foo", "0.9.0")
    _write_plugin(d, "old", "1.0.0")
    return d


@pytest.mark.asyncio
class TestPluginRegistry:
    async def test_list_local_catalog(self, catalog: Path) -> None:
        entries = await PluginRegistry(catalog).list_available()
        assert {e.name: e.version for e in entries} == {"foo": "1.0.0", "bar": "0.5.0"}

    async def test_update_upgrades_and_installs(self, catalog: Path, plugins_dir: Path) -> None:
        result = await PluginRegistry(catalog).update(plugins_dir)
        assert result == {"foo": True, "bar": True}
        assert read_installed_version(plugins_dir / "foo") == "1.0.0"
        assert read_installed_version(plugins_dir / "bar") == "0.5.0"
        assert (plugins_dir / "old").exists(), "plugins absent from the catalog must be untouched"

    async def test_update_subset(self, catalog: Path, plugins_dir: Path) -> None:
        result = await PluginRegistry(catalog).update(plugins_dir, names=["foo"])
        assert result == {"foo": True}
        assert not (plugins_dir / "bar").exists()

    async def test_update_noop_when_versions_match(self, catalog: Path, plugins_dir: Path) -> None:
        _write_plugin(plugins_dir, "foo", "1.0.0")
        await PluginRegistry(catalog).update(plugins_dir, names=["foo"])
        assert read_installed_version(plugins_dir / "foo") == "1.0.0"

    async def test_update_never_downgrades(self, catalog: Path, plugins_dir: Path) -> None:
        _write_plugin(plugins_dir, "foo", "2.0.0")
        await PluginRegistry(catalog).update(plugins_dir, names=["foo"])
        assert read_installed_version(plugins_dir / "foo") == "2.0.0"

    async def test_force_reinstalls_even_when_current(self, catalog: Path, plugins_dir: Path) -> None:
        _write_plugin(plugins_dir, "foo", "1.0.0")
        (plugins_dir / "foo" / "extra.txt").write_text("garbage", encoding="utf-8")
        await PluginRegistry(catalog).update(plugins_dir, names=["foo"], force=True)
        assert not (plugins_dir / "foo" / "extra.txt").exists()

    async def test_unsafe_name_rejected(self, catalog: Path, plugins_dir: Path) -> None:
        with pytest.raises(ValueError):
            await PluginRegistry(catalog).install("../evil", plugins_dir)

    async def test_missing_source_returns_empty(self, tmp_path: Path) -> None:
        entries = await PluginRegistry(tmp_path / "nonexistent").list_available()
        assert entries == []

    async def test_unknown_plugin_not_installed(self, catalog: Path, plugins_dir: Path) -> None:
        installed = await PluginRegistry(catalog).install("missing", plugins_dir)
        assert installed is False


@pytest.mark.asyncio
class TestCatalogParsing:
    async def test_filters_unsafe_entries(self) -> None:
        data = {
            "plugins": [
                {"name": "good", "version": "1.0.0", "url": "https://example.com/good.zip"},
                {"name": "../bad", "version": "1.0.0", "url": "https://example.com/bad.zip"},
                {"name": "priv", "version": "1.0.0", "url": "http://10.0.0.5/priv.zip"},
                {"name": "fileurl", "version": "1.0.0", "url": "file:///etc/passwd"},
            ]
        }
        entries = await _parse_catalog(data)
        assert [e.name for e in entries] == ["good"]

    async def test_non_dict_catalog_yields_empty(self) -> None:
        assert await _parse_catalog([]) == []


class TestArchiveSafety:
    def test_extract_flat_zip(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.py", _PLUGIN_PY)
            zf.writestr("manifest.json", _MANIFEST)
        dest = tmp_path / "out"
        dest.mkdir()
        _extract_zip(buf.getvalue(), dest)
        assert (dest / "plugin.py").read_text(encoding="utf-8") == _PLUGIN_PY

    def test_extract_rejects_path_traversal(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "x")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError):
            _extract_zip(buf.getvalue(), dest)

    def test_extract_rejects_absolute_path(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/evil.txt", "x")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError):
            _extract_zip(buf.getvalue(), dest)

    def test_safe_join_allows_nested_entries(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        dest.mkdir()
        target = _safe_join(dest, "sub/dir/file.txt")
        assert target == (dest / "sub" / "dir" / "file.txt").resolve()

    def test_normalize_flattens_single_top_dir(self, tmp_path: Path) -> None:
        dest = tmp_path / "pkg"
        inner = dest / "browser"
        inner.mkdir(parents=True)
        (inner / "plugin.py").write_text(_PLUGIN_PY, encoding="utf-8")
        (inner / "manifest.json").write_text(_MANIFEST, encoding="utf-8")
        _normalize_plugin_root(dest)
        assert (dest / "plugin.py").exists()
        assert not (dest / "browser").exists()
