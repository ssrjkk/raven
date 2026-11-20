"""What a Postgres column declares is a promise about the values it can hold.

Two of those promises were false at the same time and nothing could notice. The timestamp columns said
`timestamp without time zone` while every writer binds `datetime.now(UTC)`, which asyncpg refuses with a
DataError outright — so a Postgres install could not store a message and could not create a session row,
and `check_all.py` stayed green because the tests that reach a real server skip when none answers. The auth
tables said `REAL`, which on Postgres is a 4-byte float: a 2026 epoch in it steps by about two minutes, so
a session expired early or late by rounding. SQLite has no types to get wrong and answered both with
silence.

These gates read the schema text rather than a live server, which is the only way to check the promise
where no server is listening. Which blocks can reach Postgres comes from the mechanism that routes them —
`raven/core/store.py` uses `SCHEMA_POSTGRES` when a store defines one and its plain `SCHEMA` on either
dialect when it does not — plus the SQL that only Postgres accepts. A new table or store is therefore
covered the moment it is added, with no list in this file to keep current.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from raven.core.retention import POLICIES, unit_for

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("raven", "aios", "ravencode")

_TABLE_HEAD = re.compile(
    r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+[\"`]?(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_PG_ONLY = re.compile(r"\bNOW\(\)|\bBIGSERIAL\b|\bDOUBLE PRECISION\b|\bEXTRACT\s*\(", re.IGNORECASE)
_BARE_TIMESTAMP = re.compile(r"\bTIMESTAMP\b(?!Z)")
_BARE_REAL = re.compile(r"\bREAL\b")
_CONSTRAINT_LINE = re.compile(r"^\s*(PRIMARY|UNIQUE|CHECK|CONSTRAINT|FOREIGN|EXCLUDE)\b", re.IGNORECASE)
_COLUMN = re.compile(r'^\s*["`]?(?P<name>[a-z_][a-z0-9_]*)["`]?\s+(?P<type>[a-z]+(?:\s+precision)?)\b', re.IGNORECASE)
_STRING_LITERAL = re.compile(r'"""(.+?)"""|"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'', re.DOTALL)


def _source_of_value(text: str, node: ast.expr) -> str:
    """The assignment's own source, so parts spread over lines are read in the order the interpreter joins them."""
    return ast.get_source_segment(text, node) or ""


def _assignments(module: ast.Module, text: str) -> list[tuple[str, str]]:
    """(constant name, DDL source) for every module-level assignment holding a CREATE TABLE."""
    out: list[tuple[str, str]] = []
    for node in module.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        source = _source_of_value(text, node.value)
        if "CREATE TABLE" in source.upper():
            out.append((target.id, source))
    return out


def _column_definitions(body: str) -> list[str]:
    """The body cut into its column definitions, whether the table was written on one line or on ten.

    Splitting on newlines would let `CREATE TABLE x (a TEXT, applied_at TIMESTAMP)` hide a declared type at
    the end of a line the scanner had already spent on the table name, which is how six of this project's
    `_migrations` declarations are actually written.
    """
    parts: list[str] = []
    current, depth = "", 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return [" ".join(part.split()) for part in parts if part.strip()]


def _table_columns(block: str) -> dict[str, dict[str, str]]:
    """`{table: {column: declared type}}` for the tables one DDL string creates."""
    out: dict[str, dict[str, str]] = {}
    for match in _TABLE_HEAD.finditer(block):
        table = match.group(1).lower()
        # The body is what sits *between* the parentheses. Leaving the opener in the slice keeps the depth
        # counter above zero for the whole table, so no top-level comma splits a definition, the body arrives
        # as one long line, the column pattern rejects it, and every gate below this one passes on nothing.
        start = block.find("(", match.end())
        if start == -1:
            continue
        depth, cursor = 1, start + 1
        while cursor < len(block):
            char = block[cursor]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        columns: dict[str, str] = {}
        for definition in _column_definitions(block[start + 1 : cursor]):
            if _CONSTRAINT_LINE.match(definition):
                continue
            column = _COLUMN.match(definition)
            if column:
                columns[column.group("name").lower()] = re.sub(r"\s+", " ", column.group("type")).upper()
        out[table] = columns
    return out


def _sources() -> list[tuple[Path, str, ast.Module]]:
    out: list[tuple[Path, str, ast.Module]] = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "CREATE TABLE" not in text.upper():
                continue
            out.append((path, text, ast.parse(text, filename=str(path))))
    return out


def _postgres_blocks() -> list[tuple[Path, str]]:
    """Every DDL string a Postgres backend can be handed, and where it was written.

    Three routes, each read off the code: an assignment that names Postgres, a block written in syntax only
    Postgres accepts, and a store schema with no Postgres sibling, which `store.py` runs unchanged on both
    backends.
    """
    out: list[tuple[Path, str]] = []
    seen: set[tuple[Path, str]] = set()
    for path, text, module in _sources():
        assignments = _assignments(module, text)
        names = [name for name, _ in assignments]
        has_pg_sibling = any("POSTGRES" in name for name in names)
        blind_store_schema = "BaseStore" in text and "SCHEMA" in names
        for name, source in assignments:
            # the whole assignment, not its separate string parts: a table whose body is split across two
            # concatenated literals has its declared type in whichever part the scanner did not look at.
            for block in [source]:
                if "CREATE TABLE" not in block.upper():
                    continue
                routed = "POSTGRES" in name or (blind_store_schema and name == "SCHEMA" and not has_pg_sibling)
                if routed or _PG_ONLY.search(block):
                    entry = (path, block)
                    if entry not in seen:
                        seen.add(entry)
                        out.append(entry)
        # DDL written inside a method never reaches this loop's assignments, so the markers are the only route.
        for node in ast.walk(module):
            if isinstance(node, ast.Module):
                continue
            if isinstance(node, ast.Assign):
                continue
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if "CREATE TABLE" not in node.value.upper() or not _PG_ONLY.search(node.value):
                continue
            entry = (path, node.value)
            if entry not in seen:
                seen.add(entry)
                out.append(entry)
    return out


def _columns_typed_as(blocks: list[tuple[Path, str]], forbidden: set[str]) -> list[str]:
    """`file: table.column TYPE` for every Postgres-reachable column declared with one of these types."""
    return [
        f"{path.relative_to(ROOT)}: {table}.{column} {type_name}"
        for path, block in blocks
        for table, columns in _table_columns(block).items()
        for column, type_name in columns.items()
        if type_name in forbidden
    ]


def _postgres_timestamp_types() -> dict[tuple[str, str], str]:
    """Every `(table, column)` a Postgres backend can be handed, and the type it was declared with."""
    declared: dict[tuple[str, str], str] = {}
    for _path, block in _postgres_blocks():
        for table, columns in _table_columns(block).items():
            for column, type_name in columns.items():
                declared[(table, column)] = type_name
    return declared


# --- the types Postgres is promised -------------------------------------------------------------


def test_no_postgres_schema_declares_a_timestamp_whose_zone_is_left_out() -> None:
    """`timestamp without time zone` cannot take the aware datetime every writer binds, so it is not a type
    this application has ever wanted: asyncpg answers it with a DataError and the row is never written."""
    blocks = _postgres_blocks()
    assert blocks, "the Postgres DDL scan found no blocks: the probe is broken, not the schema empty"
    offenders = _columns_typed_as(blocks, {"TIMESTAMP"})
    assert not offenders, "Postgres DDL declares a naive TIMESTAMP column:\n" + "\n".join(offenders)


def test_no_postgres_schema_stores_an_epoch_in_a_four_byte_float() -> None:
    """SQLite `REAL` is an 8-byte float, Postgres `REAL` is 4, and a 2026 epoch in 4 bytes steps by about
    two minutes — enough to move a deadline nobody wrote arithmetic for."""
    offenders = _columns_typed_as(_postgres_blocks(), {"REAL"})
    assert not offenders, "Postgres DDL declares a REAL column:\n" + "\n".join(offenders)


# --- the sweep's bind matches the column it aims at --------------------------------------------


_EPOCH_TYPES = {"DOUBLE PRECISION", "REAL", "FLOAT", "FLOAT8", "NUMERIC", "DECIMAL", "BIGINT", "INTEGER"}
_INSTANT_TYPES = {"TIMESTAMPTZ"}
"""The shapes a cutoff can be compared against: `analytics_snapshots.ts` is a whole-second BIGINT, the rest
of the epoch columns are DOUBLE PRECISION, and Postgres compares a float cutoff against either."""


def test_every_policy_ages_a_column_by_the_shape_that_column_actually_stores() -> None:
    """A cutoff is compared against stored values, so the policy's unit and the DDL's type are one contract
    read from two places. `epoch_s` against a TIMESTAMPTZ is a float versus an instant — the same class of
    error that left a Postgres install unable to save a message, only on the way out of the table."""
    declared = _postgres_timestamp_types()
    assert declared, "no Postgres column type was read at all: the probe is broken, not the schema empty"

    unresolved: list[str] = []
    mismatched: list[str] = []
    for policy in POLICIES.values():
        if policy.age_column is None:
            continue
        unit = unit_for(policy, "postgresql")
        type_name = declared.get((policy.table.lower(), policy.age_column.lower()))
        if type_name is None:
            unresolved.append(f"{policy.table}.{policy.age_column}")
        elif unit == "epoch_s" and type_name not in _EPOCH_TYPES:
            mismatched.append(f"{policy.table}.{policy.age_column} is {type_name}, the policy ages it as epoch_s")
        elif unit == "timestamptz" and type_name not in _INSTANT_TYPES:
            mismatched.append(f"{policy.table}.{policy.age_column} is {type_name}, the policy ages it as an instant")
    assert not unresolved, f"no Postgres DDL declares the age columns the sweep ages: {unresolved}"
    assert not mismatched, "the sweep binds a cutoff shaped differently than the column stores time:\n" + "\n".join(
        mismatched
    )


def test_the_sweep_only_reaches_for_the_two_shapes_a_postgres_column_can_hold() -> None:
    """Read off the registry instead of a list of tables: Postgres time is either an epoch float or an
    instant now, so a policy asking for a third shape wants a type this schema forbids."""
    for policy in POLICIES.values():
        if policy.age_column is None:
            continue
        unit = unit_for(policy, "postgresql")
        assert unit in ("epoch_s", "timestamptz"), f"{policy.table}: Postgres ages {policy.age_column} as {unit!r}"


# --- the reader is not blind ---------------------------------------------------------------------


def test_the_reader_finds_the_type_in_every_shape_the_schema_is_written_in() -> None:
    """The scan used to return the table names and none of their columns, because the body it parsed still
    carried its opening parenthesis: the depth counter never fell back to zero, no top-level comma split a
    definition, and the column pattern rejected the one long line it was handed. Both gates above then
    reported a schema containing neither `TIMESTAMP` nor `REAL` — which a `declared`-non-empty assert cannot
    catch, because the tables were found and only their columns were missing."""
    shapes = {
        "CREATE TABLE a (id TEXT, seen_at TIMESTAMPTZ NOT NULL)": {"id": "TEXT", "seen_at": "TIMESTAMPTZ"},
        "CREATE TABLE IF NOT EXISTS b (\n    id BIGSERIAL PRIMARY KEY,\n    ts DOUBLE PRECISION\n)": {
            "id": "BIGSERIAL",
            "ts": "DOUBLE PRECISION",
        },
        # a comma inside nested parentheses belongs to the definition it sits in, not to the table
        "CREATE TABLE c (amount NUMERIC(10, 2), CHECK (amount >= 0), created_at TIMESTAMP)": {
            "amount": "NUMERIC",
            "created_at": "TIMESTAMP",
        },
        "CREATE TABLE d (name VARCHAR(255), updated_at TIMESTAMP DEFAULT now(), expires_at REAL)": {
            "name": "VARCHAR",
            "updated_at": "TIMESTAMP",
            "expires_at": "REAL",
        },
    }
    for block, expected in shapes.items():
        parsed = _table_columns(block)
        assert len(parsed) == 1, f"{block!r} was read as {sorted(parsed)}"
        columns = next(iter(parsed.values()))
        assert columns == expected, f"{block!r} read as {columns}"


def test_a_planted_forbidden_type_is_reported_by_the_gate_that_forbids_it() -> None:
    """The proof the two type gates are live rather than empty: a column declared with each forbidden type,
    written the way the project writes DDL, has to come back named. An offender the scanner cannot see is how
    a naive timestamp shipped behind a green suite."""
    planted = [
        (ROOT / "planted_naive.py", "CREATE TABLE t (id TEXT, created_at TIMESTAMP)"),
        (ROOT / "planted_float.py", "CREATE TABLE u (\n    id TEXT,\n    expires_at REAL\n)"),
    ]
    naive = _columns_typed_as(planted[:1], {"TIMESTAMP"})
    floats = _columns_typed_as(planted[1:], {"REAL"})
    assert naive == ["planted_naive.py: t.created_at TIMESTAMP"], naive
    assert floats == ["planted_float.py: u.expires_at REAL"], floats


def test_every_table_reachable_by_postgres_lets_the_reader_see_its_columns() -> None:
    """The invariant that would have failed on the day the parser broke, measured on the real schema rather
    than on a sample: a `CREATE TABLE` whose body yields no column is a table no gate in this file can read."""
    unread: list[str] = []
    read = 0
    for path, block in _postgres_blocks():
        tables = _TABLE_HEAD.findall(block)
        parsed = _table_columns(block)
        read += sum(len(columns) for columns in parsed.values())
        for table in tables:
            if not parsed.get(table.lower()):
                unread.append(f"{path.relative_to(ROOT)}: {table}")
    assert read > 100, f"the Postgres schema scan read {read} columns; it is reading almost nothing"
    assert not unread, f"the DDL reader parsed no column from these tables: {unread}"
