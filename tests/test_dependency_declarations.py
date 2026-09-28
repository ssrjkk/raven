"""Guard: every runtime import must be declared (or explicitly optional/lazy).

A clean-room install must not need undeclared packages. Optional integrations must be
guarded by ``try/except ImportError`` or imported lazily inside a function.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("raven", "aios", "ravencode")

# distribution name -> import name (only where they differ)
IMPORT_ALIASES = {
    "python-telegram-bot": "telegram",
    "python-dotenv": "dotenv",
    "beautifulsoup4": "bs4",
    "pillow": "pil",
    "pymupdf": "fitz",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "prometheus-client": "prometheus_client",
    "python-multipart": "multipart",
    "pyyaml": "yaml",
    "pydantic-settings": "pydantic_settings",
    "sentence-transformers": "sentence_transformers",
    "pyelftools": "elftools",
    "pywin32": "win32serviceutil",
    "ffmpeg-python": "ffmpeg",
    "y-py": "y_py",
    "py-spy": "py_spy",
    "opentelemetry-api": "opentelemetry",
    "opentelemetry-sdk": "opentelemetry",
    "types-pyyaml": "yaml",
    "types-aiofiles": "aiofiles",
    "pytest-asyncio": "pytest_asyncio",
    "pytest-cov": "pytest_cov",
    "pytest-timeout": "pytest_timeout",
    "pytest-benchmark": "pytest_benchmark",
    "allure-pytest": "allure_pytest",
}


def _declared_import_names() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    raw = list(data["project"]["dependencies"])
    for extra in data["project"]["optional-dependencies"].values():
        raw.extend(extra)
    names: set[str] = set()
    for requirement in raw:
        name = requirement.split(";")[0]
        for sep in ("[", ">=", "==", "<", "~=", "!="):
            name = name.split(sep)[0]
        name = name.strip().lower()
        names.add(name)
        names.add(name.replace("-", "_"))
        names.add(IMPORT_ALIASES.get(name, name))
    return names


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def _unconditional_imports(path: Path) -> set[str]:
    """Module-level third-party imports that are neither inside try/except nor inside a function."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - syntax errors are caught by the test suite itself
        return set()

    guarded = {node for stmt in tree.body if isinstance(stmt, ast.Try) for node in ast.walk(stmt)}
    deferred = {
        inner
        for sub in ast.walk(tree)
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
        for inner in ast.walk(sub)
    }
    local = set(PACKAGES) | {"tests", "scripts", "plugins"}
    found: set[str] = set()
    for node in ast.walk(tree):
        for name in _imported_modules(node):
            if (
                name.lower() in _declared_import_names()
                or name in sys.stdlib_module_names
                or name in local
                or node in guarded
                or node in deferred
            ):
                continue
            found.add(name)
    return found


def test_no_undeclared_imports() -> None:
    offenders: dict[str, str] = {}
    for package in PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            for name in _unconditional_imports(path):
                offenders.setdefault(name, str(path.relative_to(ROOT)))
    assert offenders == {}, (
        "Undeclared module-level imports — declare them in pyproject.toml or make them optional "
        f"(try/except ImportError) / lazy (import inside the function): {offenders}"
    )
