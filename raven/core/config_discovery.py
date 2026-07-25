from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_KEY_PATTERNS: dict[str, list[str]] = {
    "OPENAI_API_KEY": ["sk-", "sk-proj-", "sk-svcacct-"],
    "ANTHROPIC_API_KEY": ["sk-ant-"],
    "OPENROUTER_API_KEY": ["sk-or-v1-"],
    "GROQ_API_KEY": ["gsk_"],
    "BRAVE_SEARCH_API_KEY": ["BSA"],
    "PERPLEXITY_API_KEY": ["pplx-"],
    "GOOGLE_SEARCH_API_KEY": [],
    "BING_SEARCH_API_KEY": [],
    "TAVILY_API_KEY": ["tvly-"],
    "GITHUB_TOKEN": ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"],
    "GITLAB_TOKEN": ["glpat-"],
    "REPLICATE_API_TOKEN": ["r8_"],
    "HUGGINGFACE_TOKEN": ["hf_"],
    "GOOGLE_CSE_ID": [],
    "GOOGLE_CLIENT_ID": [],
    "GOOGLE_CLIENT_SECRET": [],
    "GITHUB_CLIENT_ID": [],
    "GITHUB_CLIENT_SECRET": [],
    "AZURE_API_KEY": [],
    "AZURE_ENDPOINT": [],
    "AWS_ACCESS_KEY_ID": ["AKIA"],
    "AWS_SECRET_ACCESS_KEY": [],
}


@dataclass
class DiscoveredKey:
    name: str
    value: str
    source: str
    valid: bool | None = None


@dataclass
class DiscoveryResult:
    keys: dict[str, DiscoveredKey] = field(default_factory=dict)
    providers_available: list[str] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        k = self.keys.get(name)
        if k and k.value:
            return k.value
        return default

    def is_available(self, key_name: str) -> bool:
        k = self.keys.get(key_name)
        return bool(k and k.value)


def _scan_env() -> dict[str, str]:
    found: dict[str, str] = {}
    for var_name in _KEY_PATTERNS:
        val = os.environ.get(var_name, "")
        if val:
            found[var_name] = val
    return found


def _scan_env_file() -> dict[str, str]:
    found: dict[str, str] = {}
    candidates = [Path.cwd() / ".env", Path.cwd() / ".env.local", Path.cwd() / ".env.production"]
    for env_path in candidates:
        if env_path.is_file():
            try:
                text = env_path.read_text("utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key in _KEY_PATTERNS and val:
                        found[key] = val
            except OSError:
                continue
    return found


def _scan_common_locations() -> dict[str, str]:
    found: dict[str, str] = {}
    home = Path.home()
    config_dirs = [
        home / ".raven",
        home / ".config" / "raven",
        Path.cwd() / ".raven",
    ]
    for d in config_dirs:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix in (".json", ".yaml", ".yml", ".env", ".conf"):
                    try:
                        text = f.read_text("utf-8", errors="ignore")
                        for var_name in _KEY_PATTERNS:
                            if var_name in found:
                                continue
                            for pattern in [
                                rf'{var_name}[\s=:"\']+([^\s"\']+)',
                                rf'{var_name.lower()}[\s=:"\']+([^\s"\']+)',
                            ]:
                                m = re.search(pattern, text, re.IGNORECASE)
                                if m:
                                    val = m.group(1).strip().strip("\"'")
                                    if val and len(val) > 8:
                                        found[var_name] = val
                                    break
                    except OSError:
                        continue
    return found


def _validate_key(name: str, value: str) -> bool:
    patterns = _KEY_PATTERNS.get(name, [])
    if not patterns:
        return len(value) >= 16
    return any(value.startswith(p) for p in patterns)


def discover_keys() -> DiscoveryResult:
    result = DiscoveryResult()
    all_sources: list[tuple[str, dict[str, str]]] = [
        ("env_var", _scan_env()),
        ("env_file", _scan_env_file()),
        ("config_dir", _scan_common_locations()),
    ]
    seen: dict[str, DiscoveredKey] = {}
    for source_name, source_data in all_sources:
        for var_name, value in source_data.items():
            if var_name in seen:
                continue
            valid = _validate_key(var_name, value)
            seen[var_name] = DiscoveredKey(name=var_name, value=value, source=source_name, valid=valid)

    result.keys = seen

    llm_key_map: dict[str, str] = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    for provider, key_name in llm_key_map.items():
        k = seen.get(key_name)
        if k and k.valid:
            result.providers_available.append(provider)
    if seen.get("AZURE_API_KEY"):
        result.providers_available.append("azure")
    if seen.get("AWS_ACCESS_KEY_ID") or seen.get("AWS_SECRET_ACCESS_KEY"):
        result.providers_available.append("bedrock")

    result.providers_available.append("ollama")
    if os.environ.get("VLLM_BASE_URL"):
        result.providers_available.append("vllm")

    return result


_discovery_cache: DiscoveryResult | None = None


def get_discovered_keys(force: bool = False) -> DiscoveryResult:
    global _discovery_cache
    if _discovery_cache is None or force:
        _discovery_cache = discover_keys()
        available = ", ".join(_discovery_cache.providers_available)
        logger.info("Auto-discovered LLM providers: {}", available)
    return _discovery_cache


def auto_select_model() -> str:
    result = get_discovered_keys()
    if "openrouter" in result.providers_available:
        return "openrouter/openai/o3-mini"
    if "openai" in result.providers_available:
        return "gpt-4o"
    if "anthropic" in result.providers_available:
        return "claude-sonnet-4-20250514"
    if "groq" in result.providers_available:
        return "groq/llama3-70b-8192"
    if "ollama" in result.providers_available:
        return "ollama/llama3"
    return "ollama/llama3"


def auto_model_list() -> list[str]:
    result = get_discovered_keys()
    models: list[str] = []
    if "openai" in result.providers_available:
        models.extend(["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"])
    if "anthropic" in result.providers_available:
        models.extend(["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"])
    if "openrouter" in result.providers_available:
        models.append("openrouter/openai/o3-mini")
    if "groq" in result.providers_available:
        models.extend(["groq/llama3-70b-8192", "groq/deepseek-r1-distill-qwen-32b", "groq/gemma2-9b-it"])
    if "ollama" in result.providers_available:
        models.append("ollama/llama3")
    if "vllm" in result.providers_available:
        models.append("vllm/default")
    return models or ["ollama/llama3"]
