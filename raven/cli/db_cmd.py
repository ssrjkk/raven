from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import click
from rich.console import Console

from raven.core.config import settings
from raven.core.db import DatabaseFactory

console = Console()


@click.group(name="db")
def db_group():
    """Manage the database"""


@db_group.command("migrate")
@click.option("--target", default=None, type=int, help="Target migration version")
def db_migrate(target: int | None):
    """Run pending database migrations"""

    async def _migrate():
        db = DatabaseFactory.create()
        await db.connect()
        await db.disconnect()
        console.print("[green]Migrations complete[/green]")

    asyncio.run(_migrate())


@db_group.command("backup")
@click.argument("output", default=None, required=False)
def db_backup(output: str | None):
    """Backup the database"""
    src = settings.resolved_db_path
    if not src.exists():
        console.print("[red]Database file not found[/red]")
        return
    dst = Path(output) if output else src.with_suffix(f".backup.{src.suffix}")
    shutil.copy2(str(src), str(dst))
    console.print(f"[green]Database backed up to {dst}[/green]")


@db_group.command("version")
def db_version():
    """Show current database schema version"""

    async def _version():
        db = DatabaseFactory.create()
        await db.connect()
        version = await db.migrator.get_current_version()
        await db.disconnect()
        console.print(f"Database schema version: [bold]{version}[/bold]")

    asyncio.run(_version())
