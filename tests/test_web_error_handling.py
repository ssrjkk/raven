"""The SPA may not type an error handler's parameter as `any`.

Measured before this wave: 48 handlers did — 44 `onError` callbacks and 4 `catch` blocks — and 16 of
them read `.message` with no fallback. `any` switched the type checker off at exactly the place a
failure becomes visible, so a rejection which is not an `Error` settled the error state to
`undefined` and the screen showed a button that appeared to do nothing. They now answer
`errorMessage()` from [web/src/lib/errors.ts](file:///D:/raven/web/src/lib/errors.ts), and the whole
suite type-checks: `npx tsc --noEmit` reports zero `any`-typed callback parameters in `web/src`.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
HELPER = WEB_SRC / "lib" / "errors.ts"

_CATCH_ANY = re.compile(r"catch\s*\(\s*\w+\s*:\s*any\s*\)")
_CALLBACK_ANY = re.compile(r"\(\s*\w+\s*:\s*any\s*\)\s*=>")
_USE = re.compile(r"\berrorMessage\(")
_IMPORT = re.compile(r'import\s*\{[^}]*\berrorMessage\b[^}]*\}\s*from\s*"[^"]*errors"')


def _sources() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(WEB_SRC.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".tsx"} and "node_modules" not in path.parts
    ]


def _offenders(patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    hits: list[str] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                hits.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")
    return hits


def test_no_error_handler_is_typed_as_any() -> None:
    hits = _offenders((_CATCH_ANY, _CALLBACK_ANY))
    assert not hits, "answer errorMessage() from web/src/lib/errors.ts: " + "; ".join(hits)


def test_the_helper_exists_and_every_caller_imports_it() -> None:
    assert HELPER.is_file(), "web/src/lib/errors.ts vanished"
    assert re.search(r"export function errorMessage\(", HELPER.read_text(encoding="utf-8"))
    unimported: list[str] = []
    for path in _sources():
        if path == HELPER:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _USE.search(text) and not _IMPORT.search(text):
            unimported.append(str(path.relative_to(ROOT)))
    assert not unimported, f"uses errorMessage without importing it: {unimported}"


def test_the_scanner_detects_the_shapes_it_forbids() -> None:
    """The rule above has to bite, and not fire on what the fix produces."""
    forbidden = [
        "    } catch (e: any) {\n",
        "    onError: (err: any) => setError(err.message),\n",
    ]
    for line in forbidden:
        assert _CATCH_ANY.search(line) or _CALLBACK_ANY.search(line), line
    for line in [
        '    onError: (e) => setError(errorMessage(e, "Search failed")),\n',
        "    } catch (e) {\n",
    ]:
        assert not (_CATCH_ANY.search(line) or _CALLBACK_ANY.search(line)), line
