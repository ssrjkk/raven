"""A test that patches a conditionally imported name only runs where that extra is installed.

`try: import discord ... except ImportError:` binds `discord` in the module namespace only when the
package is present. CI installs `.[dev]`, which pulls no channel extra, so a patch target like
``raven.channels.discord.channel.discord.Intents`` raises AttributeError there — or the test wraps
itself in `if HAS_DISCORD:` and passes without asserting anything. Injecting the fake name
(`monkeypatch.setattr(module, "discord", fake, raising=False)`) works on every runner.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD_PACKAGES = ("raven", "ravencode", "aios")
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception"}


def _dotted(py: Path) -> str:
    parts = list(py.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _source(py: Path) -> str:
    try:
        return py.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AssertionError(f"{py} is not utf-8: {exc}") from exc


def _imported_names(node: ast.Import | ast.ImportFrom) -> Iterable[str]:
    if isinstance(node, ast.Import):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if node.level or node.module is None:
        return []
    return [alias.asname or alias.name for alias in node.names]


def _catches_import_failure(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = [
        expr.id if isinstance(expr, ast.Name) else expr.attr
        for expr in ast.walk(handler.type)
        if isinstance(expr, (ast.Name, ast.Attribute))
    ]
    return any(name in IMPORT_ERRORS for name in names)


def conditional_names(source: str, dotted: str) -> dict[str, set[str]]:
    """Module-scoped names bound by an import that may fail, keyed by the module that binds them."""
    guarded: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Try) or not any(_catches_import_failure(h) for h in node.handlers):
            continue
        names: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                names.update(_imported_names(stmt))
        if names:
            guarded.setdefault(dotted, set()).update(names)
    return guarded


def _is_patch_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in {"patch", "setattr"}
    return isinstance(node.func, ast.Name) and node.func.id == "patch"


def patch_targets(source: str) -> list[str]:
    """Dotted-string patch targets — the form that breaks when the name was never bound."""
    targets: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args or not _is_patch_call(node):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
            targets.append(first.value)
    return targets


def find_guarded_targets(targets: Iterable[str], guarded: dict[str, set[str]]) -> list[str]:
    offenders: list[str] = []
    for target in targets:
        parts = target.split(".")
        for cut in range(1, len(parts)):
            bound = guarded.get(".".join(parts[:cut]))
            if bound and parts[cut] in bound:
                offenders.append(target)
                break
    return offenders


def production_guarded_names() -> dict[str, set[str]]:
    guarded: dict[str, set[str]] = {}
    for package in PROD_PACKAGES:
        for py in sorted((ROOT / package).rglob("*.py")):
            for dotted, names in conditional_names(_source(py), _dotted(py)).items():
                guarded.setdefault(dotted, set()).update(names)
    return guarded


def test_production_code_relies_on_conditionally_imported_names() -> None:
    # The guard below only means something if the pattern it looks for exists in the product.
    guarded = production_guarded_names()
    assert {"discord", "commands", "app_commands"} <= guarded["raven.channels.discord.channel"]
    assert {"aioimaplib", "aiosmtplib"} <= guarded["raven.channels.email.channel"]


def test_no_test_patches_a_conditionally_imported_name() -> None:
    guarded = production_guarded_names()
    offenders = [
        f"{py.relative_to(ROOT)}: {target}"
        for py in sorted((ROOT / "tests").rglob("*.py"))
        for target in find_guarded_targets(patch_targets(_source(py)), guarded)
    ]
    assert offenders == []


def test_the_guard_detects_the_pattern_it_forbids() -> None:
    # Without this, a scanner that silently stopped matching would leave the rule unchecked.
    forbidden = 'with patch("raven.channels.discord.channel.discord.Intents"):\n    pass\n'
    guarded = {"raven.channels.discord.channel": {"discord", "commands", "app_commands"}}
    assert patch_targets(forbidden) == ["raven.channels.discord.channel.discord.Intents"]
    assert find_guarded_targets(patch_targets(forbidden), guarded) == ["raven.channels.discord.channel.discord.Intents"]
    # An injected fake never names the module in a patch string, so it stays allowed.
    assert patch_targets('monkeypatch.setattr(mod, "discord", fake, raising=False)\n') == []
