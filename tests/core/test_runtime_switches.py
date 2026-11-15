"""The runtime-switch contract: one table, and every claim about it checked against the product.

The admin console used to answer `{"ok": true}` for a config write that landed in
`~/.raven/config.json` — a file no running process read — so seven switches on the screen changed
nothing until the next restart, and `RATE_LIMIT_MAX=0` was accepted and blocked every request. These
tests pin the replacement: typed validation before anything is written, the env file the gateway
actually reads, the consumer that has to be rebuilt, and an honest answer when a switch cannot take
effect in this process.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from loguru import logger

from raven.core import config as config_module
from raven.core.config import (
    Settings,
    apply_runtime_switch,
    coerce_runtime_switch,
    console_config_keys,
    refresh_settings_from_env,
    runtime_switch_keys,
    runtime_switches,
    settings,
)
from raven.core.provider_routing import PROVIDER_REQUIREMENTS
from tests.core.switch_fixtures import switch_env, switch_names

# pytest asks for a fixture by name and never reads the import, so ruff would call both bindings unused
# and every `switch_env` parameter a redefinition of one. The guard below is what keeps the pair imported.
_FIXTURES = (switch_env, switch_names)

ROOT = Path(__file__).resolve().parents[2]

VALID_OPENROUTER_KEY = "sk-or-v1-" + "a" * 32
VALID_OPENROUTER_KEY_2 = "sk-or-v1-" + "b" * 32


def _switch(attr: str) -> Any:
    return next(s for s in runtime_switches() if s.attr == attr)


_GUARD_NAME = "_runtime_switches_stay_where_the_test_left_them"


def _switch_guard() -> Iterator[None]:
    """The run's own isolation fixture, driven by hand.

    pytest refuses a fixture called from a test body, and `__wrapped__` is the generator the autouse
    registration runs for every test in the suite -- the same code, not a copy of it.
    """
    from tests.conftest import _runtime_switches_stay_where_the_test_left_them

    guard = _runtime_switches_stay_where_the_test_left_them
    return cast("Callable[[], Iterator[None]]", getattr(guard, "__wrapped__", guard))()


def _teardown_error(guard: Iterator[None]) -> AssertionError | None:
    """Run the guard's teardown half and hand back the assertion it raises, if it raises one."""
    try:
        next(guard)
    except StopIteration:
        return None
    except AssertionError as raised:
        return raised
    return None


def _known_to_loguru(name: str) -> bool:
    from loguru import logger as loguru_logger

    try:
        loguru_logger.level(name)
    except ValueError:
        return False
    return True


@pytest.fixture(autouse=True)
def _sinks_belong_to_the_next_test() -> Iterator[None]:
    """loguru keeps the sinks its process started with, so a test that re-opened them hands the next
    test the level and line shape it set — unless they are rebuilt from the restored settings."""
    yield
    from raven.core.logging import setup_logging

    setup_logging()


class TestSwitchTableContract:
    """The table is the only place these names are written down; each gate reads one product source."""

    def test_every_switch_names_a_field_settings_actually_has(self) -> None:
        missing = [s.attr for s in runtime_switches() if not hasattr(settings, s.attr)]
        assert missing == [], f"switches writing a field Settings does not have: {missing}"

    def test_the_writable_names_are_unique(self) -> None:
        attrs = [s.attr for s in runtime_switches()]
        envs = [s.env_name for s in runtime_switches()]
        assert len(set(attrs)) == len(attrs) and len(set(envs)) == len(envs)

    def test_the_switch_fixtures_are_imported_not_inherited(self) -> None:
        """A switch fixture must be named by the module that uses it, never served by the directory.

        pytest resolves a fixture through the identity of the node it was parsed against
        (`_pytest.fixtures._matchfactories` only falls back to the `baseid` string when that node is
        unset), and a run collecting `tests/core/...` together with a root-level test file rebuilds the
        `tests/core` package node. Measured on the order
        `test_config.py test_onboard.py test_runtime_switches.py`: 17 tests died with
        "fixture 'switch_env' not found" while every single-file run of the same three files was green.
        A fixture imported into the module is parsed against that module's own node, which is in the
        chain by construction.
        """
        import tests.core.switch_fixtures as fixtures

        provided = {"switch_env", "switch_names"}
        assert provided <= {name for name in vars(fixtures) if name in provided}

        requesting: list[str] = []
        unguarded: list[str] = []
        for path in sorted((ROOT / "tests" / "core").glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            used = provided & {
                arg.arg
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            }
            if not used:
                continue
            requesting.append(path.name)
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "tests.core.switch_fixtures"
                for alias in node.names
            }
            # `switch_env` asks for `switch_names`, so importing only the one a test names by hand
            # leaves the dependency unresolved in exactly the way the directory used to be.
            if not provided <= imported:
                unguarded.append(f"{path.name} imports {sorted(imported) or 'nothing'}")
        assert len(requesting) >= 3, f"the probe found {len(requesting)} consumers — the fixture names moved"
        assert unguarded == [], f"switch fixtures requested without importing both: {unguarded}"

    def test_every_switch_env_name_is_in_the_example_env(self) -> None:
        documented = set(re.findall(r"^([A-Z0-9_]+)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
        missing = sorted(s.env_name for s in runtime_switches() if s.env_name not in documented)
        assert missing == [], f"switches documented nowhere in .env.example: {missing}"

    def test_every_switch_env_name_is_in_the_configuration_reference(self) -> None:
        docs = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
        missing = sorted(s.env_name for s in runtime_switches() if s.env_name not in docs)
        assert missing == [], f"switches documented nowhere in docs/configuration.md: {missing}"

    def test_the_runtime_switches_table_in_the_docs_is_the_code_table(self) -> None:
        """The prose table is a restatement, so it is checked against the product line by line."""
        docs = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
        section = docs.split("## Runtime switches", 1)[1].split("\n#", 1)[0]
        rows = [line for line in section.splitlines() if line.startswith("| `")]
        assert len(rows) >= 5, f"the docs table parsed to {len(rows)} rows — the shape changed"
        documented: dict[str, str] = {}
        for line in rows:
            attrs = re.findall(r"`([a-z_]+)`", line.split("|")[1])
            envs = re.findall(r"`([A-Z0-9_]+)`", line.split("|")[2])
            assert len(attrs) == len(envs), f"{attrs} and {envs} do not line up"
            documented.update(zip(attrs, envs, strict=True))
        assert documented == {s.attr: s.env_name for s in runtime_switches()}

    def test_every_secret_switch_names_a_credential_the_routing_rule_demands(self) -> None:
        """A credential switch writing a name the rule does not ask for is stored, exported and read by
        nothing: the provider it was meant to unlock stays refused, and no client is ever built with it."""
        demanded = {
            env_name
            for requirements in PROVIDER_REQUIREMENTS.values()
            for requirement in requirements
            for env_name in requirement.env
        }
        unbacked = sorted(s.env_name for s in runtime_switches() if s.kind == "secret" and s.env_name not in demanded)
        assert unbacked == [], f"credential switches for a provider nothing routes by: {unbacked}"

    _CACHED_CONSUMERS: ClassVar[dict[str, tuple[str, str]]] = {
        "rate_limit_max": ("raven.core.middleware", "rate_limiter"),
    }

    def test_a_switch_with_a_cached_consumer_declares_a_rebind(self) -> None:
        """A consumer that builds its object once answers from the old value however many fields change.

        `middleware.rate_limiter` is created at import, so writing `settings.rate_limit_max` alone left
        the limiter blocking or admitting on the previous budget; the switch has to name the rebuild.
        """
        import importlib

        for attr, (module_name, object_name) in self._CACHED_CONSUMERS.items():
            assert hasattr(importlib.import_module(module_name), object_name), f"{module_name}.{object_name} is gone"
            assert _switch(attr).rebind, f"{attr} is cached by {module_name}.{object_name} but never rebound"

    def test_the_watcher_never_moves_a_switch_the_process_already_bound(self, monkeypatch) -> None:
        bound = settings.web_port
        monkeypatch.setenv("WEB_PORT", str(bound + 1))
        assert "WEB_PORT" not in refresh_settings_from_env()
        assert settings.web_port == bound, "the console would report a port nothing is listening on"

    def test_the_console_read_key_space_excludes_the_credentials(self) -> None:
        assert set(console_config_keys()) == {s.attr for s in runtime_switches() if s.kind != "secret"}
        assert not [k for k in console_config_keys() if k.endswith("_api_key")]

    def test_the_spa_posts_only_names_the_endpoint_accepts(self) -> None:
        """The one first-party client of `POST /config/key` is the Admin screen.

        It posted `openrouter_api_key` while the allowed set named a different universe, so the single
        button on the panel was guaranteed a 403. A switch renamed in Python and not in the SPA has to
        fail here, not in the browser.
        """
        posted: set[str] = set()
        for path in (ROOT / "web" / "src").rglob("*"):
            if path.suffix not in (".ts", ".tsx"):
                continue
            posted.update(
                re.findall(r"JSON\.stringify\(\{\s*key:\s*[\"']([a-z_]+)[\"']", path.read_text(encoding="utf-8"))
            )
        assert posted, "the scan found no config-key post at all — the client shape changed"
        unknown = sorted(posted - set(runtime_switch_keys()))
        assert unknown == [], f"the console posts keys the switch table does not have: {unknown}"


class TestCoercionRefusesWhatTheGatewayCannotActOn:
    @pytest.mark.parametrize(
        ("key", "raw", "fragment"),
        [
            ("rate_limit_max", "0", ">= 1"),
            ("rate_limit_max", "-5", ">= 1"),
            ("rate_limit_max", "many", "integer"),
            ("web_port", "0", ">= 1"),
            ("web_port", "70000", "<= 65535"),
            ("web_port", "8080x", "integer"),
            ("dm_policy", "opn", "must be one of"),
            ("context_visibility", "public", "must be one of"),
            ("log_level", "verbose", "must be one of"),
            ("json_log", "maybe", "true or false"),
            ("default_model", "   ", "must not be empty"),
            ("openai_api_key", "totally-not-a-key", "does not look like a real key"),
        ],
    )
    def test_the_rule_is_named_in_the_refusal(self, key: str, raw: str, fragment: str) -> None:
        with pytest.raises(ValueError) as excinfo:
            coerce_runtime_switch(key, raw)
        assert fragment in str(excinfo.value)

    def test_the_env_file_is_untouched_when_the_value_is_refused(self, switch_env: Path) -> None:
        """`apply` must validate before it writes, or a refused switch still changes the next start."""
        before = settings.rate_limit_max
        with pytest.raises(ValueError, match=">= 1"):
            asyncio.run(apply_runtime_switch("rate_limit_max", "0"))
        assert switch_env.read_text(encoding="utf-8").strip() == ""
        assert settings.rate_limit_max == before

    def test_the_domain_of_a_tiered_model_is_open_but_a_policy_is_not(self) -> None:
        assert coerce_runtime_switch("model_quality", "ollama/qwen2.5:4b") == ("ollama/qwen2.5:4b", "ollama/qwen2.5:4b")
        with pytest.raises(ValueError, match="DM_POLICY"):
            coerce_runtime_switch("dm_policy", "OPN")

    def test_integer_and_bool_switches_persist_the_canonical_text(self, switch_env: Path) -> None:
        assert coerce_runtime_switch("rate_limit_max", " 42 ") == (42, "42")
        assert coerce_runtime_switch("json_log", "TRUE") == (True, "true")
        assert coerce_runtime_switch("json_log", "off") == (False, "false")

    def test_the_log_level_domain_is_the_intersection_both_sinks_honour(self) -> None:
        """structlog falls back to INFO for a name the stdlib does not export and loguru raises, so the
        accepted set is measured from both instead of listed."""
        from loguru import logger as loguru_logger

        domain = _switch("log_level").choices()
        for name in domain:
            assert loguru_logger.level(name).no == getattr(logging, name), f"{name} means two levels"
        assert "WARN" not in domain and "WARNING" in domain
        candidates = ("TRACE", "SUCCESS", "BOMBAY_PINK", "VERBOSE")
        one_sink = tuple(n for n in candidates if _known_to_loguru(n) and getattr(logging, n, None) is None)
        assert one_sink, "no level is known to only one sink any more -- the exclusion below measures nothing"
        assert not set(one_sink) & set(domain), f"a one-sink name entered the domain: {one_sink}"

    def test_a_library_registering_a_stdlib_level_does_not_move_the_domain(self, monkeypatch) -> None:
        """The domain is a property of the two sinks, not of what this process happened to import.

        uvicorn's `Config.configure_logging()` writes `TRACE = 5` into `logging`'s process-global name
        registry, and the probe used to read that registry, so `LOG_LEVEL=TRACE` was accepted by a
        gateway that had built a uvicorn config and refused by one that had not -- measured in the unit
        stage of a full gate, where an earlier file made the registry gain the name and this switch
        then answered a different domain than the one the docs promise.
        """
        before = _switch("log_level").choices()
        # The registry has no unregister API, so the write goes through monkeypatch and is undone.
        monkeypatch.setitem(logging._nameToLevel, "TRACE", 5)
        assert logging.getLevelNamesMapping()["TRACE"] == 5, (
            "the stdlib registry stopped being a dict: probe is vacuous"
        )
        assert "TRACE" not in vars(logging), "the stdlib now exports TRACE as a constant -- both sinks honour it"
        assert _switch("log_level").choices() == before

    def test_the_visibility_domain_is_the_enum_that_filters_the_context(self) -> None:
        from raven.core.security.context_filter import ContextVisibility

        assert set(_switch("context_visibility").choices()) == {str(value) for value in ContextVisibility}

    def test_every_policy_the_switch_accepts_the_startup_validator_accepts(self) -> None:
        """`gateway_runner` calls `validate_settings()` before it binds a channel, so a switch that
        accepts a policy the validator refuses would let the console stop the next start."""
        for value in _switch("dm_policy").choices():
            candidate = Settings(  # type: ignore[call-arg]
                _env_file=None, dm_policy=value, web_secret_key=settings.web_secret_key
            )
            assert candidate.validate_settings() is True
        refused = Settings(  # type: ignore[call-arg]
            _env_file=None, dm_policy="opn", web_secret_key=settings.web_secret_key
        )
        with pytest.raises(ValueError, match="DM_POLICY"):
            refused.validate_settings()


class TestApplyChangesTheRunningGateway:
    def test_a_model_switch_lands_in_the_env_file_and_on_the_live_settings(self, switch_env: Path) -> None:
        result = asyncio.run(apply_runtime_switch("default_model", "ollama/qwen2.5:4b"))
        assert result.applied is True and result.restart_required is False
        assert settings.default_model == "ollama/qwen2.5:4b"
        assert "DEFAULT_MODEL=ollama/qwen2.5:4b" in switch_env.read_text(encoding="utf-8")
        assert result.env_file == str(switch_env)

    def test_the_live_limiter_is_rebuilt_not_just_the_setting(self, switch_env: Path) -> None:
        from raven.core import middleware

        before = middleware.rate_limiter.max_requests
        asyncio.run(apply_runtime_switch("rate_limit_max", str(before + 7)))
        assert settings.rate_limit_max == before + 7
        assert middleware.rate_limiter.max_requests == before + 7, "the middleware kept the old budget"

    def test_the_console_sink_stops_answering_at_the_new_level(self, switch_env: Path, monkeypatch) -> None:
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stderr", captured)
        asyncio.run(apply_runtime_switch("log_level", "WARNING"))
        logger.info("SWITCH-INFO-{}", 1)
        logger.warning("SWITCH-WARNING-{}", 2)
        text = captured.getvalue()
        assert "SWITCH-WARNING-2" in text and "SWITCH-INFO-1" not in text

    def test_json_log_changes_the_shape_of_the_lines_written(self, switch_env: Path) -> None:
        from raven.core.logging import setup_logging

        log_path = Path(settings.resolved_log_file)
        asyncio.run(apply_runtime_switch("json_log", "true"))
        setup_logging()
        logger.warning("SWITCH-JSON-MARKER")
        last = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert json.loads(last)["message"] == "SWITCH-JSON-MARKER"

        asyncio.run(apply_runtime_switch("json_log", "false"))
        setup_logging()
        logger.warning("SWITCH-PLAIN-MARKER")
        last = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert not last.startswith("{") and "SWITCH-PLAIN-MARKER" in last

    def test_a_restart_bound_switch_is_stored_without_moving_the_bound_value(self, switch_env: Path) -> None:
        bound = settings.web_port
        result = asyncio.run(apply_runtime_switch("web_port", str(bound + 1)))
        assert result.applied is False and result.restart_required is True
        assert any("restart" in w for w in result.warnings)
        assert settings.web_port == bound, "the console would report a port nothing is listening on"
        assert f"WEB_PORT={bound + 1}" in switch_env.read_text(encoding="utf-8")

    def test_a_credential_never_comes_back_in_the_answer(self, switch_env: Path) -> None:
        result = asyncio.run(apply_runtime_switch("openrouter_api_key", VALID_OPENROUTER_KEY))
        assert result.secret is True and "value" not in result.as_dict()
        assert VALID_OPENROUTER_KEY not in json.dumps(result.as_dict())
        assert VALID_OPENROUTER_KEY in switch_env.read_text(encoding="utf-8")
        assert settings.openrouter_api_key.get_secret_value() == VALID_OPENROUTER_KEY

    def test_a_rotated_credential_reaches_the_next_call(self, switch_env: Path) -> None:
        """The console used to drop the cached provider itself; the router now compares what its cached
        client was built with against what is configured, and replaces it on the next call."""
        from raven.core.instrumented import InstrumentedLLMProvider
        from raven.core.llm.providers.openai import OpenRouterProvider
        from raven.core.llm.router import default_llm_router

        router = default_llm_router()
        asyncio.run(apply_runtime_switch("openrouter_api_key", VALID_OPENROUTER_KEY))
        first = router._get_provider("openrouter/deepseek-chat")
        assert router._get_provider("openrouter/deepseek-chat") is first, "the client was rebuilt every call"

        asyncio.run(apply_runtime_switch("openrouter_api_key", VALID_OPENROUTER_KEY_2))
        second = router._get_provider("openrouter/deepseek-chat")
        assert second is not first, "the next call signed with the retired key"
        assert isinstance(first, InstrumentedLLMProvider) and isinstance(second, InstrumentedLLMProvider)
        assert isinstance(second._wrapped, OpenRouterProvider)
        assert second._wrapped.api_key.get_secret_value() == VALID_OPENROUTER_KEY_2
        assert isinstance(first._wrapped, OpenRouterProvider)
        assert first._wrapped.http.is_closed, "the client built with the retired key was left open"

    def test_a_credential_edited_by_hand_reaches_the_next_call(self, switch_env: Path, monkeypatch) -> None:
        """Nothing rebinds on this path but the watcher: the value is exported into the process, copied
        onto the live settings and the router decides the rest for itself."""
        from raven.core.instrumented import InstrumentedLLMProvider
        from raven.core.llm.providers.openai import OpenRouterProvider
        from raven.core.llm.router import LLMRouter

        monkeypatch.setenv("OPENROUTER_API_KEY", VALID_OPENROUTER_KEY)
        refresh_settings_from_env()
        router = LLMRouter()
        try:
            first = router._get_provider("openrouter/deepseek-chat")
            assert isinstance(first, InstrumentedLLMProvider)
            assert isinstance(first._wrapped, OpenRouterProvider)
            assert first._wrapped.api_key.get_secret_value() == VALID_OPENROUTER_KEY

            monkeypatch.setenv("OPENROUTER_API_KEY", VALID_OPENROUTER_KEY_2)
            assert "OPENROUTER_API_KEY" in refresh_settings_from_env()
            second = router._get_provider("openrouter/deepseek-chat")
            assert second is not first, "the next call signed with the retired key"
            assert isinstance(second, InstrumentedLLMProvider)
            assert isinstance(second._wrapped, OpenRouterProvider)
            assert second._wrapped.api_key.get_secret_value() == VALID_OPENROUTER_KEY_2
        finally:
            asyncio.run(router.cleanup())

    def test_a_key_that_appeared_by_hand_stops_being_refused(self, switch_env: Path, monkeypatch) -> None:
        """Refusing an unset credential is decided from the discovery scan, which only the console
        refreshed before: an export outside the env files left the gateway answering "is not set" for a
        key the process already had."""
        from raven.core import config_discovery
        from raven.core.instrumented import InstrumentedLLMProvider
        from raven.core.llm.providers.groq import GroqProvider
        from raven.core.llm.router import LLMRouter

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        # Only the process is asked here: a credential in the operator's own .env would answer for a key
        # this test does not have.
        monkeypatch.setattr(config_discovery, "_scan_env_file", lambda: {})
        monkeypatch.setattr(config_discovery, "_scan_common_locations", lambda: {})
        config_discovery.get_discovered_keys(force=True)
        router = LLMRouter()
        try:
            with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
                router._get_provider("groq/openai/gpt-oss-120b")

            monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "c" * 32)
            refresh_settings_from_env()
            provider = router._get_provider("groq/openai/gpt-oss-120b")
            assert isinstance(provider, InstrumentedLLMProvider)
            assert isinstance(provider._wrapped, GroqProvider)
        finally:
            asyncio.run(router.cleanup())

    def test_a_canary_credential_is_named_instead_of_being_accepted_quietly(self, switch_env: Path) -> None:
        result = asyncio.run(apply_runtime_switch("openrouter_api_key", "sk-or-v1-honeytoken-abc123456789"))
        assert any("canary" in w for w in result.warnings), result.warnings

    def test_an_export_outside_the_env_files_is_reported_as_the_reason_it_may_not_hold(
        self, switch_env: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "shell/wins-at-next-start")
        result = asyncio.run(apply_runtime_switch("default_model", "ollama/qwen2.5:4b"))
        assert any("exported outside the env files" in w for w in result.warnings), result.warnings

    def test_a_consumer_that_refuses_to_rebind_is_reported_not_swallowed(self, switch_env: Path, monkeypatch) -> None:
        from raven.core import middleware

        def _boom() -> Any:
            raise RuntimeError("limplier refused")

        monkeypatch.setattr(middleware, "build_rate_limiter", _boom)
        result = asyncio.run(apply_runtime_switch("rate_limit_max", "99"))
        assert result.applied is False
        assert any("refused to rebind" in w for w in result.warnings), result.warnings


class TestTheWatcherReadsTheSameTable:
    def test_the_environment_moves_the_switch_and_names_what_moved(self, switch_env: Path, monkeypatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_MAX", "33")
        changed = refresh_settings_from_env()
        assert "RATE_LIMIT_MAX" in changed
        assert settings.rate_limit_max == 33

    def test_a_value_the_switch_cannot_hold_is_named_and_left_alone(self, monkeypatch) -> None:
        before = settings.dm_policy
        monkeypatch.setenv("DM_POLICY", "opn")
        changed = refresh_settings_from_env()
        assert "DM_POLICY" not in changed
        assert settings.dm_policy == before, "a typo in .env must not decide how DMs are admitted"

    def test_an_unset_name_does_not_wipe_a_discovered_value(self, monkeypatch) -> None:
        monkeypatch.delenv("RATE_LIMIT_MAX", raising=False)
        assert settings.rate_limit_max > 0

    def test_nothing_is_reported_when_the_environment_already_agrees(self) -> None:
        refresh_settings_from_env()
        assert refresh_settings_from_env() == []

    def test_a_working_key_is_adopted_without_its_shape_being_questioned(self, switch_env: Path, monkeypatch) -> None:
        """The shape check is for a human typing a credential into the console; a gateway copying its
        own environment must not silently keep signing with a retired key."""
        monkeypatch.setenv("OPENAI_API_KEY", "a-proxy-gateway-key-with-an-odd-prefix")
        assert "OPENAI_API_KEY" in refresh_settings_from_env()
        assert settings.openai_api_key.get_secret_value() == "a-proxy-gateway-key-with-an-odd-prefix"


class TestTheRunKeepsTheBudgetItStartedWith:
    """Calibration for `tests/conftest.py::_runtime_switches_stay_where_the_test_left_them`.

    `rate_limit_middleware` shares one limiter across every `TestClient` in the process, keyed by the
    one address the client reports, so a test that leaves `RATE_LIMIT_MAX` at 33 spends the budget of
    every file that runs after it: the calls answer 429 and the test that wrote the value passes. The
    guard is the only thing between that leak and a suite that is green on a slow machine, so it is
    checked here the way the switches are -- by making it catch a real leak and put it back.
    """

    def test_a_leaked_switch_is_named_and_put_back(self) -> None:
        from raven.core import middleware
        from raven.core.middleware import RateLimiter

        guard = _switch_guard()
        before = settings.rate_limit_max
        limiter = middleware.rate_limiter
        next(guard)
        settings.rate_limit_max = 33
        middleware.rate_limiter = RateLimiter(max_requests=33, window_seconds=60.0)

        error = _teardown_error(guard)
        assert error is not None, "the guard let a switch leak into the rest of the run"
        assert "rate_limit_max" in str(error) and "middleware.rate_limiter" in str(error)
        assert settings.rate_limit_max == before, "naming the leak is not enough, the next test needs the budget"
        assert middleware.rate_limiter is limiter

    def test_an_exported_name_is_named_and_taken_back_out(self, monkeypatch) -> None:
        """The env half of the same switch, because it leaks where the settings half cannot.

        `write_env_value` and `apply_runtime_switch` export the name into the process, and a test that
        cleared it with `monkeypatch.delenv(name, raising=False)` registered nothing to put back, so the
        value outlived the test silently -- `tests/core/test_config_watcher.py` left `DEFAULT_MODEL`
        exported and an unrelated test two files later moved `settings.default_model` with
        `refresh_settings_from_env()` and was blamed for it. The guard has to name the export on the
        test that made it, and restoring means the absent case too: an empty string is not absent.
        """
        guard = _switch_guard()
        before = os.environ.get("DEFAULT_MODEL")
        next(guard)
        monkeypatch.setenv("DEFAULT_MODEL", "ollama/hf.co/mradermacher/doot:Q4_K_M")

        error = _teardown_error(guard)
        assert error is not None, "the guard let an exported switch name outlive the test"
        assert "DEFAULT_MODEL exported" in str(error)
        assert os.environ.get("DEFAULT_MODEL") == before, (
            "the name has to come back exactly as the test found it, absent included"
        )

    def test_the_guard_runs_whether_or_not_a_test_asks_for_it(self) -> None:
        """A snapshot a leaking test has to remember to request is a snapshot it will not request.

        The registration is the isolation, so it is read off the conftest that installs it instead of
        assumed: the file this suite runs from has to keep the guard autouse.
        """
        tree = ast.parse((ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
        definition = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == _GUARD_NAME),
            None,
        )
        assert definition is not None, f"tests/conftest.py no longer defines {_GUARD_NAME}"
        decorators = [ast.unparse(node) for node in definition.decorator_list]
        assert any("autouse=True" in node for node in decorators), decorators


class TestHoneytokenTripwire:
    """The scan is driven by the table that mints the canaries; the copy it replaced listed four names."""

    def test_every_canary_name_is_scanned(self, monkeypatch) -> None:
        from raven.core.watermark import HONEYTOKEN_API_KEYS

        for name, token in HONEYTOKEN_API_KEYS.items():
            monkeypatch.setenv(name, token)
            assert name in config_module.honeytoken_hits(), f"{name} canary would pass unnoticed"

    def test_a_real_credential_is_not_flagged(self, monkeypatch) -> None:
        from raven.core.watermark import HONEYTOKEN_API_KEYS

        for name in HONEYTOKEN_API_KEYS:
            monkeypatch.setenv(name, "real-value-that-is-not-a-canary")
        assert config_module.honeytoken_hits() == []


def _operator_env_state() -> tuple[bool, int, int]:
    path = ROOT / ".env"
    try:
        stat = path.stat()
    except OSError:
        return (False, -1, -1)
    return (True, stat.st_size, stat.st_mtime_ns)


class TestAnUnpinnedWriteCannotReachTheOperator:
    """`apply_runtime_switch` writes the last existing env-file candidate, which on an install is the
    operator's own `.env`. Measured: one run of the admin endpoint tests left `DEFAULT_MODEL=gpt-4o` in
    the repository's own `.env` — a value that came from a test, in a gitignored file with nothing to
    restore it,
    pointing the gateway at a provider this install has no key for. The session fixture in
    `tests/conftest.py` appends this run's temp file so it wins the precedence race; this is its
    calibration, and `tests/conftest.py::_operator_env_file_is_not_a_test_fixture` names the test that
    writes the real file anyway.
    """

    def test_an_unpinned_switch_write_lands_in_a_file_this_run_owns(
        self, monkeypatch: pytest.MonkeyPatch, switch_names: None
    ) -> None:
        monkeypatch.setattr(settings, "default_model", settings.default_model)
        before = _operator_env_state()

        result = asyncio.run(apply_runtime_switch("default_model", "ollama/qwen2.5:4b"))

        written = Path(result.env_file)
        assert written != ROOT / ".env", f"the switch was written to the operator's file: {written}"
        assert _operator_env_state() == before, "the operator's .env changed while this test ran"
        assert "DEFAULT_MODEL=ollama/qwen2.5:4b" in written.read_text(encoding="utf-8")

    def test_the_writers_and_the_reader_resolve_the_same_file(self) -> None:
        """A redirect that only moved the writer would leave `read_env_value` answering elsewhere."""
        from raven.core.config import env_file_candidates, read_env_value, write_env_value

        target = config_module.effective_env_file()
        assert env_file_candidates()[-1] == target
        write_env_value("SWITCH_PRECEDENCE_PROBE", "written")
        assert read_env_value("SWITCH_PRECEDENCE_PROBE") == "written"
        assert target.is_file() and target != ROOT / ".env"


def _cascade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *bodies: str) -> list[Path]:
    """The whole env-file cascade, written here, lowest precedence first.

    The candidate list is replaced rather than appended to: a reader that also walked the operator's own
    ``.env`` would answer a test about credentials this run does not own, and would then export them into
    the process through the very function under test.
    """
    paths: list[Path] = []
    for index, body in enumerate(bodies):
        path = tmp_path / f".env.{index}"
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(path) for path in paths])
    return paths


@contextlib.contextmanager
def _environment_of_a_fresh_start(*names: str) -> Iterator[None]:
    """Hold the named values out of the process for the block, exactly as a start that was handed only
    the files would hold them, and put back what this process had on the way out."""
    taken = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in taken.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestTheEnvFileIsOneFormatWithOneParser:
    """The file Settings loads, the file the watcher pushes and the file a switch writes, read one way.

    ``Settings`` reads the env files through pydantic-settings; everything else in the process asked
    ``os.environ``, and there is no ``load_dotenv`` in this tree -- measured on 2026-11-14, with
    ``TELEGRAM_BOT_TOKEN`` present in the file its own ``Settings`` had just read, a fresh process answered
    ``configured_channels() == []``. The fix is one parser and one adoption step, so these tests pin what
    the parser hands over (quotes gone, ``export`` honoured, non-names refused), which file wins, and what
    adoption may and may not touch.
    """

    def test_a_quoted_value_is_handed_over_unquoted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import parse_env_file

        path = _cascade(
            tmp_path,
            monkeypatch,
            'PLAIN=value\nDOUBLE="double quoted"\nSINGLE=\'single quoted\'\nPARTIAL=nested="inside"\n# a comment\n\n',
        )[0]
        assert parse_env_file(path) == {
            "PLAIN": "value",
            "DOUBLE": "double quoted",
            "SINGLE": "single quoted",
            "PARTIAL": 'nested="inside"',
        }

    def test_the_shell_spelling_of_an_assignment_is_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """python-dotenv honours ``export NAME=…``; a reader that refused it would drop a real credential."""
        from raven.core.config import parse_env_file

        path = _cascade(tmp_path, monkeypatch, "export TELEGRAM_BOT_TOKEN=123456:abc\n")[0]
        assert parse_env_file(path) == {"TELEGRAM_BOT_TOKEN": "123456:abc"}

    def test_a_name_that_is_not_env_shaped_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import parse_env_file

        path = _cascade(tmp_path, monkeypatch, "lower_case=1\n9BAD=2\nOK_NAME=3\nnot-an-assignment\n")[0]
        assert parse_env_file(path) == {"OK_NAME": "3"}

    def test_a_value_that_would_break_the_reader_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.config import apply_env_files_to_environ, parse_env_file

        path = _cascade(
            tmp_path,
            monkeypatch,
            "PATH=C:\\Windows\\system32\nPYTHONPATH=/tmp/evil\nHOME=/tmp/home\nRAVEN_SECRET_KEY=abc\nKEEP=1\n",
        )[0]
        assert parse_env_file(path) == {"KEEP": "1"}
        with _environment_of_a_fresh_start("KEEP"):
            apply_env_files_to_environ()
            assert os.environ["KEEP"] == "1"
        assert os.environ.get("PYTHONPATH") != "/tmp/evil"

    def test_the_last_file_to_assign_a_name_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.config import env_file_values

        _cascade(
            tmp_path,
            monkeypatch,
            "DEFAULT_MODEL=from/the/root/file\nONLY_LOW=1\n",
            "DEFAULT_MODEL=from/the/user/file\n",
        )
        values = env_file_values()
        assert values["DEFAULT_MODEL"] == "from/the/user/file"
        assert values["ONLY_LOW"] == "1"

    def test_adoption_fills_what_the_environment_lacks_and_leaves_an_export_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.config import apply_env_files_to_environ

        _cascade(tmp_path, monkeypatch, "FROM_FILE_ONLY=value\nOUTRANKED=from-file\n")
        monkeypatch.setenv("OUTRANKED", "from-the-shell")
        with _environment_of_a_fresh_start("FROM_FILE_ONLY"):
            applied = apply_env_files_to_environ()
            assert "FROM_FILE_ONLY" in applied
            assert "OUTRANKED" not in applied
            assert os.environ["FROM_FILE_ONLY"] == "value"
            assert os.environ["OUTRANKED"] == "from-the-shell"

    def test_a_channel_credential_in_a_file_reaches_the_channel_only_after_adoption(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.channel_config import configured_channels
        from raven.core.config import apply_env_files_to_environ

        _cascade(tmp_path, monkeypatch, "SIGNAL_API_URL=http://127.0.0.1:8080\n")
        with _environment_of_a_fresh_start("SIGNAL_API_URL"):
            assert "signal" not in configured_channels()
            apply_env_files_to_environ()
            assert "signal" in configured_channels()

    def test_an_export_agreeing_with_any_file_in_the_cascade_is_not_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The warning is for an export that beats the files, not for one that repeats them.

        The copy this replaced compared only ``effective_env_file()``, so a name the operator set in
        ``<root>/.env`` -- the file that wins when the user file does not mention it -- was reported as
        overshadowing its own value, on every write, forever.
        """
        from raven.core.config import overshadowing_env_value

        _cascade(tmp_path, monkeypatch, "RATE_LIMIT_MAX=99\n", "WEB_PORT=19000\n")
        monkeypatch.setenv("RATE_LIMIT_MAX", "99")
        assert overshadowing_env_value("RATE_LIMIT_MAX") is None
        monkeypatch.setenv("WEB_PORT", "19000")
        assert overshadowing_env_value("WEB_PORT") is None
        monkeypatch.setenv("RATE_LIMIT_MAX", "7")
        assert overshadowing_env_value("RATE_LIMIT_MAX") == "7"

    def test_a_canary_held_only_in_a_file_still_trips_the_tripwire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from raven.core.config import honeytoken_hits
        from raven.core.watermark import HONEYTOKEN_API_KEYS

        name, token = next(iter(HONEYTOKEN_API_KEYS.items()))
        _cascade(tmp_path, monkeypatch, f'{name}="{token}"\n')
        with _environment_of_a_fresh_start(name):
            assert name in honeytoken_hits()
