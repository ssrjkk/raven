from __future__ import annotations

import click
from rich.console import Console

from raven.cli.service import (
    service_install as _install,
)
from raven.cli.service import (
    service_remove as _remove,
)
from raven.cli.service import (
    service_restart as _restart,
)
from raven.cli.service import (
    service_start as _start,
)
from raven.cli.service import (
    service_status as _status,
)
from raven.cli.service import (
    service_stop as _stop,
)

console = Console()


@click.group(name="service")
def service_group():
    """Manage Raven as a platform-native service"""


@service_group.command("install")
def service_install():
    """Install Raven as a service (Windows/Systemd/Launchd)"""
    _install()


@service_group.command("start")
def service_start():
    """Start the Raven service"""
    _start()


@service_group.command("stop")
def service_stop():
    """Stop the Raven service"""
    _stop()


@service_group.command("status")
def service_status():
    """Show Raven service status"""
    _status()


@service_group.command("remove")
def service_remove():
    """Remove the Raven service"""
    _remove()


@service_group.command("restart")
def service_restart():
    """Restart the Raven service"""
    _restart()
