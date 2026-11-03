"""Regenerate the gateway page's command table from the handlers that answer them.

`/help` builds its text from the command registry in
`raven/core/gateway/commands/help.py`; the site's copy of the same list was hand-written, which is
how a page ends up advertising commands that no longer exist and hiding ones that do. This script
rewrites the block between the `commands:start` and `commands:end` markers in `site/gateway.html`,
so the published table is the registry rather than a copy of it.

Run it after adding, renaming or re-describing a command:

    python scripts/record_site_commands.py

It refuses to write when the handlers it found are not the ones `Gateway._register_commands`
installs, so a command added to a module but never registered cannot reach the page.
"""

from __future__ import annotations

import html
import importlib
import inspect
import pkgutil
import re
from pathlib import Path

from raven.core.gateway import commands as commands_package
from raven.core.gateway.commands.base import CommandHandler
from raven.core.gateway.commands.help import command_entries
from raven.core.gateway.commands.registry import CommandRegistry

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_PAGE = ROOT / "site" / "gateway.html"
GATEWAY_SOURCE = ROOT / "raven" / "core" / "gateway" / "gateway.py"
START = "                <!-- commands:start -->"
END = "                <!-- commands:end -->"
REGISTERED_RE = re.compile(r"self\.commands\.register\((\w+)\(self\)\)")


class _NeverRun:
    """Handlers read the gateway only when a command executes, never while being listed."""


def listed_registry() -> CommandRegistry:
    registry = CommandRegistry()
    package_path = Path(commands_package.__file__).resolve().parent
    for module_info in pkgutil.iter_modules([str(package_path)]):
        module = importlib.import_module(f"raven.core.gateway.commands.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if not issubclass(obj, CommandHandler) or obj is CommandHandler or inspect.isabstract(obj):
                continue
            registry.register(obj(_NeverRun()))
    return registry


def registered_class_names() -> set[str]:
    return set(REGISTERED_RE.findall(GATEWAY_SOURCE.read_text(encoding="utf-8")))


def render_rows(entries: list[tuple[str, str]]) -> str:
    rows: list[str] = []
    for call, description in entries:
        rows.append("                                <tr>")
        rows.append(f"                                    <th scope=\"row\"><code>{html.escape(call)}</code></th>")
        rows.append(f"                                    <td>{html.escape(description)}</td>")
        rows.append("                                </tr>")
    return "\n".join(rows)


def block(entries: list[tuple[str, str]]) -> str:
    count = len(entries)
    return "\n".join([
        START,
        '                <details class="matrix">',
        f"                    <summary>The {count} commands you can type on any channel, by name</summary>",
        '                    <div class="table-wrap">',
                        "                        <table>",
        f"                            <caption>The {count} chat commands the gateway dispatches</caption>",
        "                            <thead>",
        "                                <tr>",
        '                                    <th scope="col">You type</th>',
        '                                    <th scope="col">What the gateway does</th>',
        "                                </tr>",
        "                            </thead>",
        "                            <tbody>",
        render_rows(entries),
        "                            </tbody>",
        "                        </table>",
        "                    </div>",
        "                </details>",
        END,
    ])


def main() -> int:
    registry = listed_registry()
    handlers = {type(handler).__name__ for handler in registry.list_commands()}
    expected = registered_class_names()
    missing = sorted(expected - handlers)
    unregistered = sorted(handlers - expected)
    if missing or unregistered:
        print(f"Refusing to write: gateway registers {sorted(expected)}")
        if missing:
            print(f"  no such handler in the command package: {missing}")
        if unregistered:
            print(f"  handler the gateway never registers: {unregistered}")
        return 1

    entries = command_entries(registry)
    page = GATEWAY_PAGE.read_text(encoding="utf-8")
    if START not in page or END not in page:
        print(f"Refusing to write: {GATEWAY_PAGE.name} lost its commands:start/commands:end markers")
        return 1
    head, _, tail = page.partition(START)
    _, _, rest = tail.partition(END)
    updated = head + block(entries) + rest
    if updated == page:
        print(f"{GATEWAY_PAGE.name}: already current ({len(entries)} commands)")
        return 0
    GATEWAY_PAGE.write_text(updated, encoding="utf-8")
    print(f"{GATEWAY_PAGE.name}: wrote {len(entries)} command rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
