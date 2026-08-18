from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from re import Match
from typing import Any, cast

from loguru import logger

from ravencode.config.models import (
    AgentDef,
    ProviderConfig,
)

_VAR_RE = re.compile(r"\{env:(\w+)(?::([^}]+))?\}|\{file:([^}]+)\}")


def resolve_variables(value: str) -> str:
    def _replace(m: Match[str]) -> str:
        if m.group(1):
            return os.environ.get(m.group(1), m.group(2) or "")
        if m.group(3):
            p = Path(m.group(3))
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
            return ""
        return ""

    return _VAR_RE.sub(_replace, value)


def resolve_vars_in_dict(data: Any) -> Any:
    if isinstance(data, str):
        return resolve_variables(data)
    if isinstance(data, dict):
        return {k: resolve_vars_in_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_vars_in_dict(item) for item in data]
    return data


_COMMENT_RE = re.compile(r'(?:"(?:[^"\\]|\\.)*"|[^"#]*)(#|//).*')


def strip_jsonc(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith(("//", "#")):
            continue
        m = _COMMENT_RE.search(line)
        if m and m.group(1):
            before = line[: m.start(1)].rstrip()
            lines.append(before)
        else:
            lines.append(line)
    return "\n".join(lines)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


_CONFIG_PATHS: list[tuple[str, Path]] = []


def _add_source(name: str, path: Path) -> None:
    _CONFIG_PATHS.append((name, path))


def _load_jsonc(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    cleaned = strip_jsonc(text)
    return cast(dict[str, Any], json.loads(cleaned))


def _default_config_paths(project_dir: str | Path) -> list[tuple[str, Path]]:
    p = Path(project_dir).resolve()
    paths: list[tuple[str, Path]] = []

    global_cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    if global_cfg.exists():
        paths.append(("global", global_cfg))

    env_cfg = os.environ.get("OPENCODE_CONFIG")
    if env_cfg:
        paths.append(("env", Path(env_cfg)))

    for name in ("opencode.json", "opencode.jsonc", "ravencode.json", "ravencode.jsonc"):
        candidate = p / name
        if candidate.exists():
            paths.append(("project", candidate))
            break

    for name in (".opencode", ".ravencode"):
        dot_dir = p / name
        if dot_dir.is_dir() and (dot_dir / "config.json").exists():
            paths.append((f"dot_{name.lstrip('.')}", dot_dir / "config.json"))
            break

    inline = os.environ.get("RAVENCODE_CONFIG_CONTENT")
    if inline:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(inline)
            tmp_path = Path(f.name)
        paths.append(("inline", tmp_path))

    return paths


@dataclass
class RavenConfig:
    model: str = ""
    small_model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 30
    timeout: int = 120
    plan_mode: bool = False
    auto_format: bool = True
    use_cache: bool = True
    confirm_dangerous: bool = True
    diff_preview: bool = True
    proactive_scan: bool = True
    workspace_path: str = ""
    theme: str = "opencode"
    format_on_save: bool = True

    providers: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    lsp_servers: list[dict[str, Any]] = field(default_factory=list)
    formatters: list[dict[str, Any]] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    disabled_providers: list[str] = field(default_factory=list)
    enabled_providers: list[str] = field(default_factory=list)
    experimental: dict[str, Any] = field(default_factory=dict)

    _raw: dict[str, Any] = field(default_factory=dict)
    _source: str = "default"

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "unknown") -> RavenConfig:
        return cls(
            model=data.get("model", ""),
            small_model=data.get("small_model", ""),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
            max_steps=data.get("max_steps", 30),
            timeout=data.get("timeout", 120),
            plan_mode=data.get("plan_mode", False),
            auto_format=data.get("auto_format", True),
            use_cache=data.get("use_cache", True),
            confirm_dangerous=data.get("confirm_dangerous", True),
            diff_preview=data.get("diff_preview", True),
            proactive_scan=data.get("proactive_scan", True),
            workspace_path=data.get("workspace_path", ""),
            theme=data.get("theme", "opencode"),
            format_on_save=data.get("format_on_save", True),
            providers=data.get("providers", []),
            permissions=data.get("permissions", []),
            agents=data.get("agents", []),
            mcp_servers=data.get("mcp_servers", []),
            lsp_servers=data.get("lsp_servers", []),
            formatters=data.get("formatters", []),
            instructions=data.get("instructions", []),
            disabled_providers=data.get("disabled_providers", []),
            enabled_providers=data.get("enabled_providers", []),
            experimental=data.get("experimental", {}),
            _raw=data,
            _source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "small_model": self.small_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "plan_mode": self.plan_mode,
            "auto_format": self.auto_format,
            "use_cache": self.use_cache,
            "confirm_dangerous": self.confirm_dangerous,
            "diff_preview": self.diff_preview,
            "proactive_scan": self.proactive_scan,
            "workspace_path": self.workspace_path,
            "theme": self.theme,
            "format_on_save": self.format_on_save,
            "providers": self.providers,
            "permissions": self.permissions,
            "agents": self.agents,
            "mcp_servers": self.mcp_servers,
            "lsp_servers": self.lsp_servers,
            "formatters": self.formatters,
            "instructions": self.instructions,
            "disabled_providers": self.disabled_providers,
            "enabled_providers": self.enabled_providers,
            "experimental": self.experimental,
        }

    def resolve_providers(self) -> list[ProviderConfig]:
        result = []
        for p in self.providers:
            result.append(
                ProviderConfig(
                    id=p.get("id", ""),
                    name=p.get("name", ""),
                    api_key=p.get("api_key", ""),
                    base_url=p.get("base_url", ""),
                    models=p.get("models", []),
                    options=p.get("options", {}),
                )
            )
        return result

    def resolve_agents(self) -> list[AgentDef]:
        result = []
        for a in self.agents:
            result.append(
                AgentDef(
                    name=a.get("name", ""),
                    type=a.get("type", "subagent"),
                    description=a.get("description", ""),
                    prompt=a.get("prompt", ""),
                    model=a.get("model", ""),
                    temperature=a.get("temperature"),
                    max_steps=a.get("max_steps", 30),
                    permissions=a.get("permissions", {}),
                    disabled=a.get("disabled", False),
                    hidden=a.get("hidden", False),
                    options=a.get("options", {}),
                )
            )
        return result


_config_instance: RavenConfig | None = None


class ConfigLoader:
    """Loads and merges config from multiple sources."""

    def __init__(self, project_dir: str | Path | None = None) -> None:
        self._project_dir = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
        self._sources: list[tuple[str, dict[str, Any]]] = []
        self._merged: RavenConfig | None = None

    def discover(self) -> list[tuple[str, Path]]:
        return _default_config_paths(self._project_dir)

    def load_all(self) -> RavenConfig:
        sources: list[dict[str, Any]] = []
        source_names: list[str] = []

        for name, path in _default_config_paths(self._project_dir):
            try:
                data = _load_jsonc(path)
                resolved = resolve_vars_in_dict(data)
                sources.append(resolved)
                source_names.append(name)
                logger.debug("Loaded config from {} ({})", name, path)
            except Exception as e:
                logger.warning("Failed to load config from {} ({}): {}", name, path, e)

        merged: dict[str, Any] = {}
        for name, data in zip(source_names, sources, strict=False):
            merged = deep_merge(merged, data)
            logger.debug("Merged config from {}", name)

        env_overrides = self._load_env_overrides()
        if env_overrides:
            merged = deep_merge(merged, env_overrides)
            source_names.append("env_overrides")

        self._sources = list(zip(source_names, sources, strict=False))
        self._merged = RavenConfig.from_dict(merged, source="+".join(source_names) or "default")

        global _config_instance
        _config_instance = self._merged
        return self._merged

    def _load_env_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        model = os.environ.get("RAVENCODE_MODEL")
        if model:
            overrides["model"] = model
        temperature = os.environ.get("RAVENCODE_TEMPERATURE")
        if temperature:
            with contextlib.suppress(ValueError):
                overrides["temperature"] = float(temperature)
        max_steps = os.environ.get("RAVENCODE_MAX_STEPS")
        if max_steps:
            with contextlib.suppress(ValueError):
                overrides["max_steps"] = int(max_steps)
        theme = os.environ.get("RAVENCODE_THEME")
        if theme:
            overrides["theme"] = theme
        return overrides

    @property
    def config(self) -> RavenConfig:
        if self._merged is None:
            return self.load_all()
        return self._merged

    def reload(self) -> RavenConfig:
        self._merged = None
        return self.load_all()

    def get_source_paths(self) -> list[tuple[str, Path]]:
        return self.discover()


def load_config_file(path: str | Path) -> RavenConfig:
    p = Path(path).resolve()
    data = _load_jsonc(p)
    resolved = resolve_vars_in_dict(data)
    return RavenConfig.from_dict(resolved, source=str(p))


def get_config(project_dir: str | Path | None = None) -> RavenConfig:
    global _config_instance
    if _config_instance is not None and project_dir is None:
        return _config_instance
    loader = ConfigLoader(project_dir)
    return loader.load_all()
