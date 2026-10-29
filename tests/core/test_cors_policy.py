"""CORS entries must mean what they say.

`*` next to credentialed requests is not a lockdown: Starlette answers a wildcard with the caller's
own Origin, so any site can read a logged-in user's responses. A wildcard subdomain fails the other
way -- it is matched literally, so the operator believes they opened `https://*.example.com` while
nothing matches. Both are refused instead of being silently wrong, and the gateway has to build the
middleware out of the same two settings the validation reads.
"""

from __future__ import annotations

import pathlib

import pytest

from raven.core.config import SafeSecretStr, Settings


def make(origins: str, credentials: bool) -> Settings:
    return Settings(
        web_secret_key=SafeSecretStr("test-secret"),
        web_cors_origins=origins,
        web_cors_allow_credentials=credentials,
    )


def test_a_wildcard_with_credentials_is_refused() -> None:
    with pytest.raises(ValueError, match=r"any origin read"):
        make("*", True)


def test_a_wildcard_subdomain_is_refused_even_without_credentials() -> None:
    with pytest.raises(ValueError, match=r"matched literally"):
        make("https://*.example.com", False)


def test_a_wildcard_is_accepted_only_for_a_public_api() -> None:
    settings = make("*", False)
    assert settings.cors_origin_list == ["*"]
    assert settings.web_cors_allow_credentials is False


def test_explicit_origins_are_parsed_and_trimmed() -> None:
    settings = make(" http://localhost:5173 , https://raven.example.test ", True)
    assert settings.cors_origin_list == ["http://localhost:5173", "https://raven.example.test"]


@pytest.mark.parametrize("origins", ["localhost:5173", "ftp://host", "//host", "http://"])
def test_an_entry_that_is_not_an_origin_is_refused(origins: str) -> None:
    with pytest.raises(ValueError, match="is not usable"):
        make(origins, True)


def test_an_empty_list_means_no_cross_origin_access_at_all() -> None:
    settings = make("", True)
    assert settings.cors_origin_list == []


def test_the_gateway_builds_cors_from_the_validated_settings() -> None:
    """No second copy of the origin list, and no fallback that quietly reopens localhost."""
    source = pathlib.Path("raven/cli/gateway_runner.py").read_text(encoding="utf-8")
    assert "allow_origins=settings.cors_origin_list" in source
    assert "allow_credentials=settings.web_cors_allow_credentials" in source
    assert "http://localhost:5173\"" not in source
