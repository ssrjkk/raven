import pytest
from pydantic import SecretStr

from raven.core.config import SafeSecretStr
from raven.core.llm.factory import LLMProviderFactory
from raven.core.logging import _mask_secret_str


def test_safe_secret_str_masking():
    secret = SafeSecretStr("super-secret-key")
    assert str(secret) == "**********"
    assert secret.get_secret_value() == "super-secret-key"


def test_safe_secret_str_bool():
    assert bool(SafeSecretStr("")) is False
    assert bool(SafeSecretStr("sk-test")) is True


def test_safe_secret_str_empty_str():
    assert str(SafeSecretStr("")) == ""
    assert SafeSecretStr("").get_secret_value() == ""


def test_safe_secret_str_or_empty():
    result = SafeSecretStr("") or "default"
    assert result == "default"


def test_safe_secret_str_or_nonempty():
    result = SafeSecretStr("key") or "default"
    assert isinstance(result, SafeSecretStr)
    assert result.get_secret_value() == "key"


def test_safe_secret_str_with_pydantic():
    from pydantic import BaseModel

    class TestModel(BaseModel):
        api_key: SafeSecretStr = SafeSecretStr("")

    m = TestModel()
    assert str(m.api_key) == ""
    assert m.api_key.get_secret_value() == ""

    m2 = TestModel(api_key=SafeSecretStr("sk-test"))
    assert m2.api_key.get_secret_value() == "sk-test"
    assert str(m2.api_key) == "**********"


def test_llm_provider_factory_create():
    api_key = SecretStr("sk-test")
    provider = LLMProviderFactory.create("openai", api_key=api_key)
    assert provider is not None
    import httpx
    assert isinstance(provider.http, httpx.AsyncClient)  # type: ignore[attr-defined]
    assert str(provider.api_key) == "**********"  # type: ignore[attr-defined]
    assert provider.api_key.get_secret_value() == "sk-test"  # type: ignore[attr-defined]


def test_llm_provider_factory_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        LLMProviderFactory.create("nonexistent", api_key=SecretStr("test"))


def test_secret_str_filter_masks_in_loguru():
    secret = SecretStr("super-secret-value")
    record: dict[str, object] = {
        "args": (secret, "visible"),
    }
    assert _mask_secret_str(record) is True
    assert record["args"] == ("**********", "visible")


def test_secret_str_filter_non_secret_unchanged():
    record: dict[str, object] = {
        "args": ("hello", 42, ["list"]),
    }
    assert _mask_secret_str(record) is True
    assert record["args"] == ("hello", 42, ["list"])


def test_secret_str_filter_no_args():
    record: dict[str, object] = {}
    assert _mask_secret_str(record) is True


@pytest.mark.asyncio
async def test_provider_cleanup_zeroes_key():
    api_key = SecretStr("sk-test123")
    provider = LLMProviderFactory.create("openai", api_key=api_key)
    assert provider.api_key.get_secret_value() == "sk-test123"  # type: ignore[attr-defined]
    await provider.cleanup()
    assert provider.api_key.get_secret_value() == ""  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_base_llm_provider():
    from raven.core.llm import BaseLLMProvider
    provider = BaseLLMProvider(api_key=SecretStr("sk-base"), base_url="https://test.api")
    assert provider._get_api_key() == "sk-base"
    assert provider._api_key.get_secret_value() == "sk-base"
    await provider.cleanup()
    assert provider._api_key.get_secret_value() == ""
