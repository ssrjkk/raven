"""A permission check must ask the role table, not a list of role names typed at the call site.

Measured before this wave: eight handlers wrote `if role not in ("admin", "superadmin")`. Two things
were wrong with that. `Role` has four members — admin, user, viewer, banned — so `superadmin` named a
role that cannot exist in the store, yet `auth_middleware` copies whatever role string a session
carries onto `request.state.user_role`, so a caller minted as `superadmin` was an admin at those eight
endpoints and a stranger everywhere else. And a role the permission table does grant a right to still
got a 403, because the check never consulted that table.

Both ask `raven/core/auth/guards.py` now, which answers from `rbac.has_permission`.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from raven.core.auth.models import Role

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTION_DIRS = ("raven", "aios", "ravencode")
PHANTOM_ROLE = "superadmin"


def _sources() -> Iterator[tuple[str, ast.Module]]:
    for directory in PRODUCTION_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            yield rel, ast.parse(path.read_text(encoding="utf-8", errors="ignore"))


def _role_lists(tree: ast.Module) -> list[tuple[int, str]]:
    """`role not in ("admin", ...)` — an authorization test against literal role names.

    LLM message parts are also called `role` and compared against `("user", "tool")`, so the gate keys
    on the name only an authorization list can contain: `admin`.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.ops[0], (ast.In, ast.NotIn)):
            continue
        if "role" not in ast.unparse(node.left).lower():
            continue
        for comparator in node.comparators:
            if not isinstance(comparator, (ast.Tuple, ast.Set, ast.List)) or not comparator.elts:
                continue
            literals: list[str] = []
            for element in comparator.elts:
                if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                    literals = []
                    break
                literals.append(element.value)
            if Role.ADMIN.value in literals:
                hits.append((node.lineno, ast.unparse(node)))
    return hits


def test_the_phantom_is_really_absent_from_the_role_table() -> None:
    """The rule below only means something while no such role exists."""
    assert PHANTOM_ROLE not in {r.value for r in Role}


def test_production_code_never_names_a_role_the_enum_does_not_have() -> None:
    hits = [
        f"{rel}:{node.lineno}"
        for rel, tree in _sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == PHANTOM_ROLE
    ]
    assert not hits, f"{PHANTOM_ROLE} is not a Role member: {hits}"


def test_no_permission_check_compares_a_role_against_a_hand_written_list() -> None:
    hits = [f"{rel}:{line} {expr}" for rel, tree in _sources() for line, expr in _role_lists(tree)]
    assert not hits, "ask rbac through raven/core/auth/guards.py instead: " + "; ".join(hits)


def test_the_guard_detects_the_shape_it_forbids() -> None:
    """The rule above has to bite, and has to bite only authorization lists."""
    forbidden = ast.parse('if user_role not in ("admin", "superadmin"):\n    raise HTTPException(403)\n')
    assert [expr for _, expr in _role_lists(forbidden)] == ["user_role not in ('admin', 'superadmin')"]
    for allowed_src in (
        "if not rbac.has_permission(role, Permission.ADMIN_SECRETS):\n    raise HTTPException(403)\n",
        'gemini_role = "user" if role in ("user", "tool") else "model"\n',
        "if message.get('role') in ('system',):\n    continue\n",
    ):
        assert _role_lists(ast.parse(allowed_src)) == []
