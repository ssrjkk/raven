"""Every third-party import in shipped code has to be declared somewhere.

An optional import that is named in no dependency group is not "optional", it is missing: the
provider falls back quietly and the feature the operator believes they run stops running. This is
how the voice anti-spoof check (`librosa`) became a no-op and stayed green, and the same shape still
sits in `speechbrain`, the whisper/vosk/azure STT providers, `hnswlib`, `duckduckgo_search`,
`presidio_analyzer`, `structlog` and `wandb`.

The check is a membership test on distributions, so an import whose package is spelled differently
(`PIL` -> Pillow, `telegram` -> python-telegram-bot, `whisper` -> openai-whisper) is still resolved
by what pip installs.
"""

from __future__ import annotations

import ast
import pathlib
import sys
import tomllib
from typing import Final

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_ROOTS: Final = ("raven", "ravencode", "aios")

# Import name -> distribution name, only where they differ.
IMPORT_TO_DIST: Final[dict[str, str]] = {
    "PIL": "Pillow",
    "azure": "azure-cognitiveservices-speech",
    "bs4": "beautifulsoup4",
    "discord": "discord.py",
    "docx": "python-docx",
    "duckduckgo_search": "duckduckgo-search",
    "elftools": "pyelftools",
    "ffmpeg": "ffmpeg-python",
    "gtts": "gTTS",
    "opentelemetry": "opentelemetry-api",
    "presidio_analyzer": "presidio-analyzer",
    "prometheus_client": "prometheus-client",
    "pptx": "python-pptx",
    "pydantic_settings": "pydantic-settings",
    "sentence_transformers": "sentence-transformers",
    "slack_sdk": "slack-sdk",
    "speech_recognition": "SpeechRecognition",
    "telegram": "python-telegram-bot",
    "typing_extensions": "typing-extensions",
    "whisper": "openai-whisper",
    "win32com": "pywin32",
    "pythoncom": "pywin32",
    "yaml": "PyYAML",
    "y_py": "y-py",
}


def normalize(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def third_party_imports() -> dict[str, str]:
    """Top-level external import name -> first file:line that imports it."""
    local = set(SOURCE_ROOTS) | set(sys.stdlib_module_names) | {"tests", "scripts", "__future__"}
    found: dict[str, str] = {}
    for root_name in SOURCE_ROOTS:
        for path in sorted((ROOT / root_name).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as exc:
                raise AssertionError(f"{path} cannot be parsed for its imports: {exc}") from exc
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif node.level == 0 and node.module:
                    modules = [node.module]
                for module in modules:
                    top = module.split(".")[0]
                    if top in local or top.startswith("_"):
                        continue
                    found.setdefault(top, f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def declared_distributions() -> set[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    names: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        names.extend(group)
    declared = set()
    for requirement in names:
        head = str(requirement).split("[")[0]
        for separator in ("<", ">", "=", "!", ";", "~", " ", "@"):
            head = head.split(separator)[0]
        if head and not head.startswith("raven-agent"):
            declared.add(normalize(head))
    return declared


def undeclared(declared: set[str]) -> list[tuple[str, str]]:
    misses: list[tuple[str, str]] = []
    for top, site in third_party_imports().items():
        distribution = normalize(IMPORT_TO_DIST.get(top, top))
        if distribution not in declared:
            misses.append((f"{top} (pip: {IMPORT_TO_DIST.get(top, top)})", site))
    return sorted(misses)


def test_every_shipped_import_is_a_declared_distribution() -> None:
    misses = undeclared(declared_distributions())
    assert not misses, "imports with no dependency declaration:\n" + "\n".join(
        f"  {name}  imported at {site}" for name, site in misses
    )


def test_the_detector_reports_a_dropped_declaration() -> None:
    """The gate must be able to fail: removing one declaration has to name that package."""
    declared = declared_distributions()
    for probe in ("vosk", "librosa", "hnswlib", "duckduckgo_search", "structlog", "wandb", "whisper"):
        distribution = normalize(IMPORT_TO_DIST.get(probe, probe))
        assert distribution in declared, f"{probe} is not declared at all"
        misses = dict((name.split(" ")[0], site) for name, site in undeclared(declared - {distribution}))
        assert probe in misses, f"dropping {distribution} did not make {probe} a finding"


def test_the_distribution_map_only_names_real_imports() -> None:
    imports = set(third_party_imports())
    stale = sorted(name for name in IMPORT_TO_DIST if name not in imports)
    assert not stale, f"IMPORT_TO_DIST entries no longer imported anywhere: {stale}"
