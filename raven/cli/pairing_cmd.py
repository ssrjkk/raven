from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from raven.core.db import DatabaseFactory

console = Console()


@click.group(name="pairing")
def pairing_group():
    """Manage user pairing"""


@pairing_group.command("list")
def pairing_list():
    """List pending pairing requests"""

    async def _list():
        db = DatabaseFactory.create()
        await db.connect()
        users = await db.get_pending_pairing_users()
        await db.disconnect()
        if not users:
            console.print("[yellow]No pending pairing requests[/yellow]")
            return
        table = Table(title="Pending Pairing Requests")
        table.add_column("User ID", style="cyan")
        table.add_column("Channel")
        table.add_column("Pairing Code", style="yellow")
        for u in users:
            table.add_row(u["id"], u["channel"], u.get("pairing_code", ""))
        console.print(table)

    asyncio.run(_list())


@pairing_group.command("approve")
@click.argument("code")
def pairing_approve(code: str):
    """Approve a user by pairing code"""

    async def _approve():
        db = DatabaseFactory.create()
        await db.connect()
        user = await db.get_user_by_pairing_code(code)
        if not user:
            console.print(f"[red]No user found with pairing code: {code}[/red]")
            await db.disconnect()
            return
        await db.set_user_allowed(user["id"], True)
        await db.set_pairing_code(user["id"], "")
        console.print(f"[green]User {user['id']} approved![/green]")
        await db.disconnect()

    asyncio.run(_approve())
