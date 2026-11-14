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

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from raven.core.config import Settings, settings

LOCAL_PROVIDER = "ollama"

# Providers an install serves itself: no per-call bill and no credential question. `local` is the
# in-process LoRA adapter, `vllm` a self-hosted OpenAI-compatible server.
SELF_HOSTED_PROVIDERS = frozenset({"ollama", "vllm", "local"})


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

# The credential each provider cannot work without: the router refuses out of this table, the admin
# console rotates a key into it, and `_forget_cached_provider` maps a rotated name back to the cached
# client. It is the credential-shaped slice of `PROVIDER_REQUIREMENTS` above — vertex has no row, because
# rotating a key is not a thing vertex does, and neither has a self-hosted provider.
PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "copilot": "GITHUB_TOKEN",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "azure": "AZURE_OPENAI_API_KEY",
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
