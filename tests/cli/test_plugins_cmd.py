from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from raven.cli.plugins_cmd import plugins_group
from raven.plugins.registry import read_installed_version

_PLUGIN_PY = 'async def hello() -> str:\n    return "hi"\n'


def _write_plugin(root: Path, name: str, version: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.py").write_text(_PLUGIN_PY, encoding="utf-8")
    (d / "manifest.json").write_text(
        f'{{"name":"{name}","version":"{version}"}}', encoding="utf-8"
    )


def test_cli_plugins_update_from_local_registry(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    _write_plugin(catalog, "foo", "1.0.0")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _write_plugin(plugins_dir, "foo", "0.5.0")

    runner = CliRunner()
    result = runner.invoke(
        plugins_group,
        ["update", "foo", "--registry", str(catalog), "--dir", str(plugins_dir)],
    )
    assert result.exit_code == 0, result.output
    assert read_installed_version(plugins_dir / "foo") == "1.0.0"


def test_cli_plugins_search_lists_catalog(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    _write_plugin(catalog, "foo", "1.0.0")
    _write_plugin(catalog, "bar", "2.0.0")

    runner = CliRunner()
    result = runner.invoke(plugins_group, ["search", "--registry", str(catalog)])
    assert result.exit_code == 0, result.output
    assert "foo" in result.output
    assert "1.0.0" in result.output
    assert "bar" in result.output


def test_cli_plugins_update_requires_name_or_all(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(plugins_group, ["update"])
    assert result.exit_code == 1
    assert "plugin name" in result.output.lower()


def test_cli_plugins_update_without_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("raven.cli.plugins_cmd.settings.plugin_registry_url", "")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        plugins_group, ["update", "foo", "--dir", str(plugins_dir)]
    )
    assert result.exit_code == 1
    assert "registry" in result.output.lower()
