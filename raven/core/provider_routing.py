"""One answer to "which provider does this model name ask for, and what does that provider need".

The prefix chain that decided routing was written down seven times and disagreed. The router sent
`openai/gpt-4o` and `azure/gpt-4o` — both spellings `ravencode.json` and the console's provider hints
advertise — to Ollama, and `local/<base>` too, although a provider named `local` is creatable;
`model_tiers` called groq/vertex/bedrock/copilot/vllm/azure "unknown" and handed their installs Ollama
tier ids; `raven models list` could not put a checkmark on an OpenAI default at all; the failover pool
labelled every bare `claude-*` name OpenAI and dropped it for an Anthropic-only install; the security
audit derived the provider again and passed a `bedrock/` default the router refuses. Two names in the
router's credential table were read by nothing in the tree: `GOOGLE_API_KEY`, which made `vertex/...`
unroutable whatever an operator configured, and `AZURE_API_KEY`, while `AzureProvider` reads
`AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from raven.core.config import Settings, settings

LOCAL_PROVIDER = "ollama"

# Providers an install serves itself: no per-call bill and no credential question. `local` is the
# in-process LoRA adapter, `vllm` a self-hosted OpenAI-compatible server. The settings fields are what
# those classes snapshot when the router builds them, which is why they belong to the rule and not to
# whichever surface reports them.
SELF_HOSTED_SETTINGS: dict[str, tuple[str, ...]] = {
    "ollama": ("ollama_base_url",),
    "vllm": ("vllm_base_url",),
    "local": ("llm_local_base_model", "llm_local_adapter_path"),
}

SELF_HOSTED_PROVIDERS = frozenset(SELF_HOSTED_SETTINGS)


@dataclass(frozen=True)
class Requirement:
    """One thing a provider cannot be built without.

    `env` names the environment variables the provider class itself reads — any one satisfies it — and
    `override` names the `providers_config` key that stands in for them, which is how `ravencode.json`
    hands over a credential without exporting it. Availability is asked of the discovery table, which
    scans the environment, the `.env` files and the config directories; that is also the surface the
    admin console and the tests write to.
    """

    env: tuple[str, ...]
    override: str = ""

    def describe(self) -> str:
        return " or ".join(self.env)

    def is_met(self, overrides: Mapping[str, Any]) -> bool:
        if self.override and overrides.get(self.override):
            return True
        from raven.core import config_discovery

        discovery = config_discovery.get_discovered_keys()
        return any(discovery.is_available(name) for name in self.env)


# Credentials first, then the non-secret configuration whose absence would otherwise surface as a DNS or
# HTTP error instead of a refusal. Vertex asks for no key: `VertexAIProvider` signs with an
# application-default token from `gcloud auth print-access-token`, so a mandatory key would name a
# variable nothing reads. Azure needs its endpoint as well, because the class falls back to a placeholder
# resource URL that answers to no one.
PROVIDER_REQUIREMENTS: dict[str, tuple[Requirement, ...]] = {
    "openai": (Requirement(("OPENAI_API_KEY",), "api_key"),),
    "anthropic": (Requirement(("ANTHROPIC_API_KEY",), "api_key"),),
    "openrouter": (Requirement(("OPENROUTER_API_KEY",), "api_key"),),
    "groq": (Requirement(("GROQ_API_KEY",), "api_key"),),
    "copilot": (Requirement(("GITHUB_TOKEN", "COPILOT_TOKEN"), "api_key"),),
    "bedrock": (Requirement(("AWS_ACCESS_KEY_ID",), "api_key"),),
    "azure": (
        Requirement(("AZURE_OPENAI_API_KEY",), "api_key"),
        Requirement(("AZURE_OPENAI_ENDPOINT",), "base_url"),
    ),
    "vertex": (Requirement(("VERTEX_AI_PROJECT",), "project"),),
}

PROVIDER_NAMES: frozenset[str] = frozenset(PROVIDER_REQUIREMENTS) | SELF_HOSTED_PROVIDERS

# Model ids that predate the `<provider>/<model>` contract and stay supported.
_LEGACY_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("claude",), "anthropic"),
    (("gpt", "o1", "o3"), "openai"),
    (("gemini/",), "vertex"),
)


def provider_for_model(model: str, *, ghost_mode: bool) -> str:
    """The provider a model name asks for, or `LOCAL_PROVIDER` when it names none.

    The first path segment wins whenever it names a provider this install can build, which is why
    `openrouter/openai/gpt-4o` and `groq/openai/gpt-oss-120b` are OpenRouter and Groq rather than OpenAI.
    `ghost_mode` is a parameter and not a read of the live settings because a turn that may not leave the
    machine has no provider to choose, while a caller asking what a *name* means — the failover pool, the
    security audit, which tiers still bill — has to be answered regardless of what this gateway is set to.
    """
    if ghost_mode:
        return LOCAL_PROVIDER
    name = model.strip().lower()
    if not name:
        return LOCAL_PROVIDER
    head = name.split("/", 1)[0]
    if head in PROVIDER_NAMES:
        return head
    for prefixes, provider in _LEGACY_PREFIXES:
        if name.startswith(prefixes):
            return provider
    return LOCAL_PROVIDER


def missing_requirements(provider: str, overrides: Mapping[str, Any] | None = None) -> list[str]:
    """What has to be named in the refusal that keeps `provider` from being built, worded as an operator
    has to write it. An empty list means the provider can be built, not that a call to it will succeed."""
    supplied = overrides or {}
    return [
        requirement.describe()
        for requirement in PROVIDER_REQUIREMENTS.get(provider, ())
        if not requirement.is_met(supplied)
    ]


def _as_text(value: Any) -> str:
    """The string a provider class would put in its request, whatever shape the switch handed over."""
    if value is None:
        return ""
    secret: Any = getattr(value, "get_secret_value", None)
    return str(secret()) if callable(secret) else str(value)


def _provider_inputs(provider: str, overrides: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Every value a provider class reads when it is constructed, keyed by where it comes from.

    The classes take the same shape — an override wins, otherwise the settings field or the environment
    the class itself reads — so this is what a built client snapshotted, and a change here is a change
    the client cannot see for itself.
    """
    supplied = overrides or {}
    inputs = {f"config:{name}": _as_text(value) for name, value in supplied.items()}
    for requirement in PROVIDER_REQUIREMENTS.get(provider, ()):
        override_value = _as_text(supplied.get(requirement.override)) if requirement.override else ""
        env_value = next((value for value in (credential_value(name) for name in requirement.env) if value), "")
        inputs["env:" + "|".join(requirement.env)] = override_value or env_value
    for field in SELF_HOSTED_SETTINGS.get(provider, ()):
        inputs[f"settings:{field}"] = _as_text(getattr(settings, field, ""))
    return inputs


def credential_fingerprint(provider: str, overrides: Mapping[str, Any] | None = None) -> str:
    """A digest of `_provider_inputs`, for a caller that has to notice the values moved.

    It is a digest and not the values: the router keeps one per cached provider, and copying a
    deployment's credentials into that dictionary would only widen where they can be read.
    """
    joined = "\0".join(f"{name}={value}" for name, value in sorted(_provider_inputs(provider, overrides).items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def credential_value(env_name: str) -> str:
    """What the provider class would see for `env_name` in this process.

    A Settings field when the project owns one — pydantic has already read `.env` into it — and otherwise
    the raw environment, which is what `AzureProvider`, `BedrockProvider`, `CopilotProvider` and
    `VertexAIProvider` actually read. Surfaces that report a deployment's configuration (the security
    audit) ask this instead of the discovery cache, because a heuristic match in
    `~/.raven/config.json` is not something the class will ever find.
    """
    field_name = env_name.lower()
    if field_name in Settings.model_fields:
        value: Any = getattr(settings, field_name)
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return str(value or "")
    return os.environ.get(env_name, "").strip()
