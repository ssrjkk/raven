from __future__ import annotations

import click
import requests
from rich.console import Console

console = Console()


@click.group(name="nodes")
def nodes_group():
    """Manage Raven AI nodes (iOS/Android devices)"""


@nodes_group.command("list")
def nodes_list():
    """List paired device nodes"""
    console.print("[yellow]Node system: connect iOS/Android devices via Gateway WebSocket[/yellow]")
    console.print("  iOS: https://docs.raven.ai/platforms/ios")
    console.print("  Android: https://docs.raven.ai/platforms/android")
    console.print("\nNo devices currently paired.")


@nodes_group.command("pair")
@click.argument("device_id")
@click.option("--url", default=None, help="Node URL (auto-detected if omitted)")
def nodes_pair(device_id: str, url: str | None):
    """Pair a new device node"""
    node_url = url or f"http://{device_id}:18789"
    try:
        resp = requests.post(f"{node_url.rstrip('/')}/api/v1/pair", json={"device_id": device_id}, timeout=10)
        if resp.ok:
            console.print(f"[green]Device {device_id} paired successfully ({node_url})[/green]")
        else:
            console.print(f"[red]Device {device_id} pairing failed: {resp.status_code} {resp.text}[/red]")
    except requests.RequestException as e:
        console.print(f"[red]Device {device_id} pairing failed: {e}[/red]")
