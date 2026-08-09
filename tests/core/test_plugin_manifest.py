from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from raven.core.plugin_loader import PluginLoader
from raven.plugins.manifest import PluginManifest, _version_ge


def _write_plugin_dir(tmp_path: Path, name: str, manifest: dict[str, Any] | None) -> Path:
    plugin_dir = tmp_path / name
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(
        "async def hello(name: str = 'world') -> str:\n    return f'hello {name}'\n",
        encoding="utf-8",
    )
    if manifest is not None:
        (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plugin_dir


class TestPluginManifest:
    def test_from_file_parses_fields(self, tmp_path: Path):
        mf = tmp_path / "manifest.json"
        mf.write_text(
            json.dumps(
                {
                    "name": "demo",
                    "version": "1.2.3",
                    "description": "demo plugin",
                    "author": "tester",
                    "permissions": ["network"],
                    "requires": ["requests"],
                    "min_raven_version": "0.4.0",
                }
            ),
            encoding="utf-8",
        )
        m = PluginManifest.from_file(mf)
        assert m is not None
        assert m.name == "demo"
        assert m.version == "1.2.3"
        assert m.permissions == ["network"]
        assert m.requires == ["requests"]
        assert m.min_raven_version == "0.4.0"

    def test_from_file_missing_returns_none(self, tmp_path: Path):
        assert PluginManifest.from_file(tmp_path / "nope.json") is None

    def test_from_file_invalid_json_returns_none(self, tmp_path: Path):
        mf = tmp_path / "manifest.json"
        mf.write_text("{not json", encoding="utf-8")
        assert PluginManifest.from_file(mf) is None

    def test_from_file_non_object_returns_none(self, tmp_path: Path):
        mf = tmp_path / "manifest.json"
        mf.write_text("[1, 2, 3]", encoding="utf-8")
        assert PluginManifest.from_file(mf) is None

    def test_validate_ok(self):
        m = PluginManifest(min_raven_version="0.4.0")
        assert m.validate("0.4.1") is None

    def test_validate_rejects_older_raven(self):
        m = PluginManifest(min_raven_version="1.0.0")
        assert m.validate("0.4.0") is not None

    def test_validate_ignores_empty_requirement(self):
        assert PluginManifest().validate("0.0.1") is None

    def test_version_ge(self):
        assert _version_ge("1.0.0", "1.0.0")
        assert _version_ge("1.1.0", "1.0.9")
        assert _version_ge("2.0.0", "1.9.9")
        assert not _version_ge("0.4.0", "0.5.0")
        assert not _version_ge("0.4", "0.4.1")
        assert _version_ge("0.4.1", "0.4")
        assert _version_ge("0.5.0-rc1", "0.5.0")


class TestPluginLoaderManifest:
    def test_loads_plugin_with_manifest(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(
            tmp_path, "demo", {"name": "demo", "version": "1.0.0", "min_raven_version": "0.0.1"}
        )
        loader = PluginLoader()
        tools = loader.load_from_dir(plugin_dir)
        assert len(tools) == 1
        assert tools[0].name == "demo.hello"
        manifest = loader.get_manifest("demo")
        assert manifest is not None
        assert manifest.version == "1.0.0"

    def test_loads_plugin_without_manifest(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(tmp_path, "bare", None)
        loader = PluginLoader()
        tools = loader.load_from_dir(plugin_dir)
        assert len(tools) == 1
        manifest = loader.get_manifest("bare")
        assert manifest is not None
        assert manifest.version == "0.0.0"

    def test_rejects_plugin_requiring_newer_raven(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(tmp_path, "future", {"min_raven_version": "99.0.0"})
        loader = PluginLoader()
        tools = loader.load_from_dir(plugin_dir)
        assert tools == []
        assert loader.get_manifest("future") is None

    def test_rejects_plugin_with_invalid_manifest(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(tmp_path, "broken", None)
        (plugin_dir / "manifest.json").write_text("{nope", encoding="utf-8")
        loader = PluginLoader()
        tools = loader.load_from_dir(plugin_dir)
        assert tools == []

    def test_manifests_property_and_clear(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(tmp_path, "demo", {"version": "2.0.0"})
        loader = PluginLoader()
        loader.load_from_dir(plugin_dir)
        assert "demo" in loader.manifests
        loader.clear()
        assert loader.manifests == {}

    async def test_untrusted_manifest_validation(self, tmp_path: Path):
        plugin_dir = _write_plugin_dir(tmp_path, "future", {"min_raven_version": "99.0.0"})
        loader = PluginLoader()
        results = await loader.load_untrusted_from_dir(plugin_dir)
        assert results == []
