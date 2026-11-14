"""One model-prefix→provider rule, and the guard that keeps it the only copy.

The chain was written down seven times: the router's `elif startswith` ladder, `model_tiers`' provider
family, the ✓ column of `raven models list`, the failover pool's `split("/")[0]`, the security audit's
`split("/", 1)[0]`, the bundled-model warning about tiers that still bill, and ghost mode's "is this
already a local model". They disagreed on `openai/gpt-4o`, `azure/gpt-4o` and `local/<base>`, and two of
the credential names they demanded (`GOOGLE_API_KEY`, `AZURE_API_KEY`) are read by nothing in the tree.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
import re
import textwrap
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from raven.core import config_discovery
from raven.core.config import SafeSecretStr, Settings, settings
from raven.core.llm.factory import LLMProviderFactory
from raven.core.provider_routing import (
    LOCAL_PROVIDER,
    PROVIDER_NAMES,
    PROVIDER_REQUIREMENTS,
    SELF_HOSTED_SETTINGS,
    Requirement,
    _provider_inputs,
    credential_fingerprint,
    credential_value,
    missing_requirements,
    provider_for_model,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Every model spelling the project writes down itself: `ravencode.json`, the console's provider hints,
# `.env.example`, `auto_model_list()`, the tier tables and the docs.
_ADVERTISED: list[tuple[str, str]] = [
    ("openrouter/openai/gpt-4o", "openrouter"),
    ("OPENROUTER/Anthropic/Claude-3.5-Sonnet", "openrouter"),
    ("openrouter/google/gemini-2.0-flash-001", "openrouter"),
    ("anthropic/claude-3-5-sonnet-latest", "anthropic"),
    ("claude-3-5-haiku-latest", "anthropic"),
    ("claude-sonnet-4-20250514", "anthropic"),
    ("gpt-4o", "openai"),
    ("gpt-4o-mini", "openai"),
    ("o1-mini", "openai"),
    ("o3-mini", "openai"),
    ("openai/gpt-4o", "openai"),
    ("azure/gpt-4o", "azure"),
    ("groq/openai/gpt-oss-120b", "groq"),
    ("groq/qwen/qwen3.8-27b", "groq"),
    ("vertex/gemini-2.0-flash", "vertex"),
    ("gemini/2.0-flash", "vertex"),
    ("bedrock/anthropic.claude-3", "bedrock"),
    ("copilot/gpt-4", "copilot"),
    ("vllm/llama3", "vllm"),
    ("vllm/default", "vllm"),
    ("local/unsloth/Qwen2.5-7B", "local"),
    ("ollama/llama3", "ollama"),
    ("  ollama/qwen2.5:32b  ", "ollama"),
    ("ollama/hf.co/mradermacher/DeepSeek-V4-Pro:Q4_K_M", "ollama"),
    ("llama3", LOCAL_PROVIDER),
    ("mystery/model-x", LOCAL_PROVIDER),
    ("", LOCAL_PROVIDER),
]


class _NoKeys:
    providers_available: ClassVar[list[str]] = ["ollama"]

    def is_available(self, key_name: str) -> bool:
        return False


class _AllKeys:
    providers_available: ClassVar[list[str]] = ["openai", "anthropic", "openrouter", "groq", "ollama"]

    def is_available(self, key_name: str) -> bool:
        return True


@pytest.fixture
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_discovery, "get_discovered_keys", lambda *a, **k: _NoKeys())


@pytest.mark.parametrize(("model", "provider"), _ADVERTISED)
def test_the_owner_routes_every_spelling_the_project_advertises(model: str, provider: str) -> None:
    assert provider_for_model(model, ghost_mode=False) == provider


@pytest.mark.parametrize("model", sorted({model for model, _ in _ADVERTISED}))
def test_ghost_mode_never_leaves_the_machine_for_a_model_name(model: str) -> None:
    assert provider_for_model(model, ghost_mode=True) == LOCAL_PROVIDER


def test_the_local_provider_answers_a_name_that_names_no_provider() -> None:
    assert provider_for_model("llama3.1:8b", ghost_mode=False) == LOCAL_PROVIDER


def _factory_table_names() -> set[str]:
    """The provider keys `LLMProviderFactory.create` actually dispatches on."""
    entry = ast.parse(textwrap.dedent(inspect.getsource(LLMProviderFactory.create))).body[0]
    names: set[str] = set()
    for node in ast.walk(entry):
        if isinstance(node, ast.Dict):
            names.update(key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
    return names


def test_the_owner_knows_exactly_the_providers_the_factory_can_build() -> None:
    assert _factory_table_names() == PROVIDER_NAMES


@pytest.fixture
def built_provider() -> Any:
    """One instance per hosted provider, closed whatever the assertions do."""
    created: list[Any] = []

    def _build(provider: str) -> Any:
        instance = LLMProviderFactory.create(
            provider,
            api_key=SecretStr("a" * 24),
            base_url="https://example.invalid",
            project="example-project",
        )
        created.append(instance)
        return instance

    yield _build
    asyncio.run(_close_all(created))


async def _close_all(created: list[Any]) -> None:
    for instance in created:
        await instance.cleanup()


def test_every_credential_the_rule_demands_is_one_the_provider_class_reads(built_provider: Any) -> None:
    """`GOOGLE_API_KEY` and `AZURE_API_KEY` sat in the router's table while no class read either.

    Each hosted provider is built through the factory, its own source is read, and every variable the rule
    names has to appear there — as a literal the class reads or as the Settings field it reads.
    """
    findings: list[str] = []
    for provider, requirements in PROVIDER_REQUIREMENTS.items():
        source = inspect.getsource(type(built_provider(provider)))
        for requirement in requirements:
            if not any(
                f'"{name}"' in source or f"'{name}'" in source or f"settings.{name.lower()}" in source
                for name in requirement.env
            ):
                findings.append(f"{provider}: {' or '.join(requirement.env)} read by nothing in the class")
    assert findings == []


@pytest.mark.parametrize(
    "env_name",
    sorted({name for requirements in PROVIDER_REQUIREMENTS.values() for req in requirements for name in req.env}),
)
def test_every_switch_the_rule_demands_is_one_the_discovery_scan_looks_for(env_name: str) -> None:
    assert env_name in config_discovery._KEY_PATTERNS


def test_discovery_offers_azure_only_when_both_names_the_class_reads_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key without an endpoint is an available credential and an unusable provider: the class falls back
    to a placeholder resource URL, so the pool must not offer azure on the key alone."""
    key = {"AZURE_OPENAI_API_KEY": "a" * 24}
    endpoint = {"AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com"}

    def _discover(env: dict[str, str]) -> list[str]:
        monkeypatch.setattr(config_discovery, "_scan_env", lambda: dict(env))
        monkeypatch.setattr(config_discovery, "_scan_env_file", lambda: {})
        monkeypatch.setattr(config_discovery, "_scan_common_locations", lambda: {})
        return list(config_discovery.discover_keys().providers_available)

    assert "azure" not in _discover(key)
    assert "azure" not in _discover(endpoint)
    assert "azure" in _discover({**key, **endpoint})


def test_vertex_is_a_provider_without_a_mandatory_key(no_credentials: None) -> None:
    assert not [requirement for requirement in PROVIDER_REQUIREMENTS["vertex"] if requirement.override == "api_key"]
    assert not any(name.endswith("_API_KEY") for name in PROVIDER_REQUIREMENTS["vertex"][0].env)
    assert missing_requirements("vertex") == ["VERTEX_AI_PROJECT"]


def test_azure_is_refused_by_the_names_of_what_it_actually_needs(no_credentials: None) -> None:
    assert missing_requirements("azure") == ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]


def test_an_azure_endpoint_from_the_provider_config_satisfies_the_rule(no_credentials: None) -> None:
    assert missing_requirements("azure", {"api_key": "k" * 24, "base_url": "https://x.openai.azure.com"}) == []
    assert missing_requirements("azure", {"base_url": "https://x.openai.azure.com"}) == ["AZURE_OPENAI_API_KEY"]


def test_a_self_hosted_provider_asks_no_credential_at_all(no_credentials: None) -> None:
    for provider in ("ollama", "vllm", "local"):
        assert missing_requirements(provider) == []


def test_a_hosted_provider_with_a_discovered_key_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_discovery, "get_discovered_keys", lambda *a, **k: _AllKeys())
    assert missing_requirements("openrouter") == []


def test_a_credential_handed_over_in_the_provider_config_needs_no_env_var(no_credentials: None) -> None:
    """`ravencode.json` and the admin console's critical-provider config pass a key inline; refusing such
    a call because the same key is not also exported was the router's own bug."""
    assert missing_requirements("anthropic", {"api_key": "sk-ant-" + "a" * 24}) == []


def test_credential_value_prefers_the_field_the_application_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", SafeSecretStr("sk-from-settings"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-environment")
    assert credential_value("OPENAI_API_KEY") == "sk-from-settings"
    monkeypatch.setattr(settings, "openai_api_key", SafeSecretStr(""))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert credential_value("OPENAI_API_KEY") == ""


def test_credential_value_falls_back_to_the_environment_the_class_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "aws_access_key_id" not in Settings.model_fields
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAexample")
    assert credential_value("AWS_ACCESS_KEY_ID") == "AKIAexample"
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    assert credential_value("AWS_ACCESS_KEY_ID") == ""


def test_a_requirement_describes_itself_the_way_an_operator_has_to_write_it() -> None:
    assert Requirement(("GITHUB_TOKEN", "COPILOT_TOKEN")).describe() == "GITHUB_TOKEN or COPILOT_TOKEN"


class TestWhatTheProviderWasBuiltWith:
    """The router may only reuse a cached client when the digest covers everything the provider class
    read as it was constructed: a value left out of `_provider_inputs` is a change the client never sees,
    and the call after it is signed with a credential the operator already replaced."""

    def test_a_rotated_credential_moves_the_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", SafeSecretStr("sk-or-v1-" + "a" * 32))
        before = credential_fingerprint("openrouter")
        monkeypatch.setattr(settings, "openrouter_api_key", SafeSecretStr("sk-or-v1-" + "b" * 32))
        assert credential_fingerprint("openrouter") != before

    def test_a_credential_handed_over_in_the_provider_config_moves_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", SafeSecretStr(""))
        before = credential_fingerprint("openrouter")
        handed_over = credential_fingerprint("openrouter", {"api_key": SecretStr("sk-or-v1-" + "c" * 32)})
        assert handed_over != before

    def test_two_handed_over_keys_are_two_digests(self) -> None:
        """The digest has to see through a `SecretStr`: a masked restatement would answer the same value
        for every key, and a deployment rotated through `ravencode.json` would keep its old client."""
        first = credential_fingerprint("openai", {"api_key": SecretStr("sk-" + "a" * 24)})
        second = credential_fingerprint("openai", {"api_key": SecretStr("sk-" + "b" * 24)})
        assert first != second

    def test_a_handed_over_value_the_rule_has_no_requirement_for_moves_it_too(self) -> None:
        """The provider class is built with everything the config hands over, and `timeout` is one of
        those: a digest of the names the rule knows would keep a client built with the old timeout."""
        assert credential_fingerprint("openai", {"timeout": 5}) != credential_fingerprint("openai", {"timeout": 30})

    def test_an_azure_endpoint_moves_it_though_the_key_stayed_put(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azurekey")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://first.resource.openai.azure.com")
        before = credential_fingerprint("azure")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://second.resource.openai.azure.com")
        assert credential_fingerprint("azure") != before

    def test_a_vertex_project_moves_it_although_vertex_asks_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERTEX_AI_PROJECT", "first-project")
        before = credential_fingerprint("vertex")
        monkeypatch.setenv("VERTEX_AI_PROJECT", "second-project")
        assert credential_fingerprint("vertex") != before

    def test_the_address_a_self_hosted_provider_answers_on_moves_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ollama_base_url", "http://127.0.0.1:11434")
        before = credential_fingerprint("ollama")
        monkeypatch.setattr(settings, "ollama_base_url", "http://gpu-box:11434")
        assert credential_fingerprint("ollama") != before

    def test_the_adapter_a_local_provider_serves_moves_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "llm_local_adapter_path", "models/first")
        before = credential_fingerprint("local")
        monkeypatch.setattr(settings, "llm_local_adapter_path", "models/second")
        assert credential_fingerprint("local") != before

    def test_another_providers_credential_leaves_this_one_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", SafeSecretStr("sk-ant-" + "a" * 24))
        before = credential_fingerprint("anthropic")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAexample")
        assert credential_fingerprint("anthropic") == before

    def test_an_unset_name_and_an_empty_one_are_the_same_thing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise the router would rebuild the client on every call for a name nobody ever set."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        absent = credential_fingerprint("bedrock")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "")
        assert credential_fingerprint("bedrock") == absent

    def test_the_digest_is_a_digest_and_not_a_copy_of_the_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = "sk-or-v1-" + "d" * 32
        monkeypatch.setattr(settings, "openrouter_api_key", SafeSecretStr(key))
        assert key not in credential_fingerprint("openrouter")

    def test_every_provider_the_router_can_build_has_inputs_the_digest_sees(self) -> None:
        blind = sorted(provider for provider in PROVIDER_NAMES if not _provider_inputs(provider))
        assert blind == [], f"a client of {blind} would be reused whatever was configured"

    def test_every_self_hosted_setting_is_a_field_the_settings_object_has(self) -> None:
        """Read with a default, so a name that does not exist is an invisible hole rather than an error."""
        missing = sorted(
            field for fields in SELF_HOSTED_SETTINGS.values() for field in fields if field not in Settings.model_fields
        )
        assert missing == [], f"self-hosted settings no provider class reads: {missing}"


# A provider prefix as the routing rule spells it: the `<provider>/` form and the legacy model ids.
_PROVIDER_LITERAL = re.compile(
    r"""["'](?:openrouter/|anthropic/|claude|groq/|vertex/|gemini/|bedrock/|copilot/|vllm/|azure/|local/"""
    r"""|openai/|ollama/|gpt|o1|o3)"""
)
# The other way a copy was written: `provider = model.split("/")[0]`.
_MODEL_SPLIT = re.compile(r"""\.split\(\s*["']/""")


def _copies(source: str) -> list[str]:
    """Lines in `source` that decide a provider from a model name without asking the owner.

    Read off the syntax tree, so a comment or a docstring naming `azure/gpt-4o` is not a copy: the shapes
    are a `startswith()` on a provider-prefixed literal, and an assignment to a `provider` name built by
    splitting a model id on `/`.
    """
    findings: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith":
            segment = ast.get_source_segment(source, node) or ""
            if _PROVIDER_LITERAL.search(segment):
                findings.append(f"line {node.lineno}: {segment}")
        elif isinstance(node, ast.Assign):
            targets = " ".join(getattr(target, "id", "") for target in node.targets).lower()
            value = ast.get_source_segment(source, node.value) or ""
            if "provider" in targets and _MODEL_SPLIT.search(value):
                findings.append(f"line {node.lineno}: {targets} = {value}")
    return findings


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def _copies_in(rel: str) -> list[str]:
    return [f"{rel}: {finding}" for finding in _copies(_read(rel))]


def _app_sources() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for directory in ("raven", "ravencode", "aios", "scripts")
        for path in (ROOT / directory).rglob("*.py")
    )


def test_the_owner_is_the_only_copy_of_the_rule() -> None:
    findings: list[str] = []
    for rel in _app_sources():
        if rel == "raven/core/provider_routing.py":
            continue
        findings.extend(_copies_in(rel))
    assert findings == [], f"a second reading of the model name: {findings}"


@pytest.mark.parametrize(
    "rel",
    [
        "raven/core/llm/router.py",
        "raven/core/model_tiers.py",
        "raven/cli/models_cmd.py",
        "raven/core/failover.py",
        "raven/core/heretic_model.py",
        "raven/core/config.py",
        "raven/core/security/security_audit.py",
    ],
)
def test_every_site_that_once_answered_the_question_asks_the_owner(rel: str) -> None:
    assert "provider_for_model(" in _read(rel), f"{rel} still decides routing on its own"


def test_the_copy_check_names_a_copy_and_lets_an_unrelated_split_alone() -> None:
    assert _copies('provider = model.split("/", 1)[0].strip()\n') != []
    assert _copies('mark = "X" if default_model.startswith("openrouter/") else ""\n') != []
    assert _copies('mark = "X" if default_model.startswith("claude") else ""\n') != []
    assert _copies('if name.startswith("ollama/"):\n    return LOCAL\n') != []
    assert _copies('tag = image.split(":")[0]\n') == []
    assert _copies('if name.startswith("#"):\n    return ""\n') == []
    assert _copies("# a comment about azure/gpt-4o being routed wrong\nanswer = 42\n") == []


def test_the_copy_check_scans_the_application_it_claims_to() -> None:
    sources = _app_sources()
    assert len(sources) > 400, len(sources)
    for rel in ("raven/core/llm/router.py", "ravencode/api/client.py", "aios/api/bridge.py"):
        assert rel in sources, rel
