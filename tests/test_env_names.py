from __future__ import annotations

import functools
import pathlib
import re
from typing import Any

import pytest
import yaml

from raven.core.channel_config import _LEGACY_ENV
from raven.core.config import Settings

ROOT = pathlib.Path(__file__).resolve().parents[1]

# A switch an operator or a container is handed: `NAME=value`, commented out or not.
_DECLARED = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", re.M)
# A switch named in prose, e.g. the hint "set CHANNEL_ALLOW_FROM to restrict users".
_IN_TEXT = re.compile(r"\b([A-Z][A-Z0-9_]{3,})=")
# One of the read forms the codebase uses: os.getenv("X"), os.environ.get("X"),
# os.environ["X"], env.get("X") and the membership test `"X" in os.environ`.
_READ = re.compile(r"(?:getenv|environ\.get|environ\[|env\.get)\s*\(?\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']")
_MEMBERSHIP = re.compile(r"[\"']([A-Z][A-Z0-9_]{2,})[\"']\s+in\s+os\.environ")
# Vite reads build-time names as properties of import.meta.env, not through os.environ.
_VITE_READ = re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]{2,})")
# A switch read through a module constant: WEB_DIST_ENV_VAR = "RAVEN_WEB_DIST".
_BOUND = re.compile(r"^([A-Z0-9_]+)\s*=\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']", re.M)


@functools.lru_cache(maxsize=1)
def _python_blob() -> str:
    parts: list[str] = []
    for directory in ("raven", "ravencode", "aios", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


@functools.lru_cache(maxsize=1)
def _consumed() -> frozenset[str]:
    """Every environment name the application can read for itself."""
    names: set[str] = set()
    for field_name, field in Settings.model_fields.items():
        names.add(field_name.upper())
        for alias in (field.alias, field.validation_alias):
            names.update(literal.upper() for literal in re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", str(alias)))
    for mapping in _LEGACY_ENV.values():
        names.update(mapping)
    blob = _python_blob()
    names.update(_READ.findall(blob))
    names.update(_MEMBERSHIP.findall(blob))
    for constant, value in _BOUND.findall(blob):
        if re.search(r"(?:getenv|environ\.get|environ\[|env\.get|environ)\s*\(?\s*" + re.escape(constant), blob):
            names.add(value)
    return frozenset(names)


def _generated(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The files the onboarding CLIs actually hand to an operator."""

    from raven.cli import init_cmd, setup_cmd

    llm = {"provider": "openrouter", "default_model": "openrouter/openai/gpt-4o", "api_key": ""}
    channels = {"telegram": {"enabled": True, "token": "tg-token"}, "discord": {"enabled": False, "token": ""}}
    security = {"dm_policy": "pairing", "web_port": 18888}

    out: dict[str, str] = {}
    example = tmp_path / "generated.env.example"
    init_cmd._write_env_example(llm, channels, security, example)
    out["raven init .env.example"] = example.read_text(encoding="utf-8")

    real = tmp_path / "generated.env"
    init_cmd._write_real_env(llm, channels, security, real)
    out["raven init .env"] = real.read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    out["raven setup --free .env"] = setup_cmd._write_env("llama3").read_text(encoding="utf-8")


    out[".env.example"] = (ROOT / ".env.example").read_text(encoding="utf-8")
    return out


def _compose_names() -> dict[str, set[str]]:
    """Environment entries the generated compose files inject into the raven container."""
    from raven.cli import deploy_cmd

    deploy_cmd._init_compose_templates()
    collected: dict[str, set[str]] = {}
    for mode, content in deploy_cmd.COMPOSE_CONTENT.items():
        parsed: dict[str, Any] = yaml.safe_load(content)
        entries = parsed["services"]["raven"].get("environment") or []
        collected[f"raven deploy {mode}"] = {str(entry).split("=")[0].strip() for entry in entries}
    return collected


def _hint_names() -> set[str]:
    from raven.core.security.security_audit import SecurityAudit

    names: set[str] = set()
    for check in SecurityAudit().run_all():
        names.update(_IN_TEXT.findall(f"{check.message} {check.fix_hint() or ''}"))
    return names


def _emitted(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    emitted = {label: sorted(set(_DECLARED.findall(text))) for label, text in _generated(tmp_path, monkeypatch).items()}
    for label, names in _compose_names().items():
        emitted[label] = sorted(names)
    emitted["raven security audit hints"] = sorted(_hint_names())
    return emitted


def _inert(emitted: dict[str, list[str]], consumed: frozenset[str] | set[str]) -> list[tuple[str, str]]:
    return sorted((label, name) for label, names in emitted.items() for name in names if name not in consumed)


def test_the_sweep_counts_real_switches_on_both_sides() -> None:
    assert len(_consumed()) > 150
    assert (ROOT / ".env.example").is_file()


def test_no_switch_the_tooling_hands_out_is_one_the_application_ignores(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _inert(_emitted(tmp_path, monkeypatch), _consumed()) == []


def test_the_sweep_reads_the_files_it_claims_to(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    emitted = _emitted(tmp_path, monkeypatch)
    assert sum(len(names) for names in emitted.values()) > 120
    assert len(emitted[".env.example"]) > 100
    assert "raven init .env" in emitted and "raven deploy full" in emitted


def test_the_check_names_a_switch_the_application_never_reads(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _inert({"raven init .env": ["RAVEN_NO_SUCH_SWITCH"]}, _consumed()) == [
        ("raven init .env", "RAVEN_NO_SUCH_SWITCH")
    ]


def test_the_generated_stack_declares_no_service_the_application_cannot_reach() -> None:
    from raven.cli import deploy_cmd

    deploy_cmd._init_compose_templates()
    services: set[str] = set()
    for content in deploy_cmd.COMPOSE_CONTENT.values():
        services.update((yaml.safe_load(content)["services"] or {}).keys())
    # grafana and prometheus consume /api/admin/metrics/prometheus, which the admin API
    # serves. Any other service would be infrastructure the application never talks to.
    assert services == {"raven", "grafana", "prometheus"}


def test_the_web_bundle_advertises_only_variables_it_reads() -> None:
    web = ROOT / "web"
    declared = set(_DECLARED.findall((web / ".env.example").read_text(encoding="utf-8")))
    read: set[str] = set()
    for path in sorted((web / "src").rglob("*.ts*")):
        if path.suffix in {".ts", ".tsx"}:
            read.update(_VITE_READ.findall(path.read_text(encoding="utf-8", errors="ignore")))
    assert declared, "the bundle's example file vanished"
    assert read, "no import.meta.env read anywhere in web/src"
    assert sorted(declared - read) == []
