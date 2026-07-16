from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.group(name="devices")
def devices_group():
    """Alias for nodes commands"""


@devices_group.command("list")
def devices_list():
    """List paired devices"""
    console.print("[yellow]See 'raven nodes list' for device information[/yellow]")
