from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from raven.cli.gateway_runner import create_gateway
from raven.core.config import settings
from raven.plugins.registry import PluginRegistry

console = Console()


@click.group(name="plugins")
def plugins_group():
    """Manage plugins"""


def _plugin_dirs() -> list[Path]:
    plugins_dir = Path(__file__).parent.parent / "plugins"
    return sorted(
        (d for d in plugins_dir.iterdir() if d.is_dir() and d.name != "__pycache__"),
        key=lambda d: d.name,
    )


def _resolve_registry(registry: str | None) -> str:
    source = registry or settings.plugin_registry_url
    if not source:
        console.print(
            "[red]No plugin registry configured. Set PLUGIN_REGISTRY_URL or pass --registry.[/red]"
        )
        raise SystemExit(1)
    return source


@plugins_group.command("search")
@click.option("--registry", default=None, help="Catalog URL or directory (overrides PLUGIN_REGISTRY_URL)")
def plugins_search(registry: str | None):
    """List plugins available in the registry"""
    source = _resolve_registry(registry)
    try:
        entries = asyncio.run(PluginRegistry(source).list_available())
    except Exception as exc:
        console.print(f"[red]Catalog error: {exc}[/red]")
        raise SystemExit(1) from None
    table = Table(title="Available Plugins")
    table.add_column("Plugin", style="cyan")
    table.add_column("Version")
    table.add_column("Description")
    if not entries:
        table.add_row("(none)", "-", "No plugins advertised")
    for entry in entries:
        table.add_row(entry.name, entry.version, entry.description or "-")
    console.print(table)


@plugins_group.command("update")
@click.argument("plugin_name", required=False)
@click.option("--all", "update_all", is_flag=True, help="Update every plugin in the registry")
@click.option("--force", is_flag=True, help="Reinstall even when the installed version matches")
@click.option("--registry", default=None, help="Catalog URL or directory (overrides PLUGIN_REGISTRY_URL)")
@click.option(
    "--dir",
    "dest_dir",
    default=None,
    help="Target plugins directory (defaults to the bundled raven/plugins)",
)
def plugins_update(
    plugin_name: str | None,
    update_all: bool,
    force: bool,
    registry: str | None,
    dest_dir: str | None,
):
    """Install or update plugins from the registry"""
    if not plugin_name and not update_all:
        console.print("[red]Provide a plugin name or use --all[/red]")
        raise SystemExit(1)
    source = _resolve_registry(registry)
    dest = Path(dest_dir) if dest_dir else Path(__file__).parent.parent / "plugins"
    try:
        result = asyncio.run(
            PluginRegistry(source).update(dest, names=[plugin_name] if plugin_name else None, force=force)
        )
    except Exception as exc:
        console.print(f"[red]Update error: {exc}[/red]")
        raise SystemExit(1) from None
    for name, ok in result.items():
        console.print(f"[green]{name}[/green]: {'updated' if ok else 'no change'}")
    if not result:
        console.print("[yellow]No plugins matched the request.[/yellow]")


@plugins_group.command("list")
def plugins_list():
    """List loaded plugins"""
    gateway = create_gateway()
    loader = gateway.plugin_loader
    for pdir in _plugin_dirs():
        loader.load_from_dir(pdir)
    table = Table(title="Loaded Plugins")
    table.add_column("Plugin", style="cyan")
    table.add_column("Version")
    table.add_column("Tools")
    namespaces = {t.name.split(".", 1)[0] for t in loader.tools}
    for pdir in _plugin_dirs():
        manifest = loader.get_manifest(pdir.name)
        version = manifest.version if manifest else "?"
        tools_in_plugin = [t for t in loader.tools if t.name.startswith(f"{pdir.name}.")]
        if tools_in_plugin:
            table.add_row(pdir.name, version, ", ".join(t.name for t in tools_in_plugin))
        elif pdir.name in namespaces:
            table.add_row(pdir.name, version, "(no tools)")
    if not loader.tools:
        table.add_row("(none)", "-", "No plugins loaded")
    console.print(table)


@plugins_group.command("info")
@click.argument("plugin_name")
def plugins_info(plugin_name: str):
    """Show manifest details for a plugin"""
    gateway = create_gateway()
    loader = gateway.plugin_loader
    target = None
    for pdir in _plugin_dirs():
        if pdir.name == plugin_name:
            target = pdir
            break
    if target is None:
        console.print(f"[red]Plugin not found: {plugin_name}[/red]")
        raise SystemExit(1)
    loader.load_from_dir(target)
    manifest = loader.get_manifest(plugin_name)
    if manifest is None:
        console.print(f"[red]Plugin failed to load: {plugin_name}[/red]")
        raise SystemExit(1)
    table = Table(title=f"Plugin: {plugin_name}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Name", manifest.name or plugin_name)
    table.add_row("Version", manifest.version)
    table.add_row("Author", manifest.author or "-")
    table.add_row("Description", manifest.description or "-")
    table.add_row("Permissions", ", ".join(manifest.permissions) or "-")
    table.add_row("Requires", ", ".join(manifest.requires) or "-")
    table.add_row("Min Raven Version", manifest.min_raven_version or "-")
    table.add_row("Entry", manifest.entry)
    console.print(table)
