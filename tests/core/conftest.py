"""Isolation for the tests that move a runtime switch on a live settings object."""

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pytest

from raven.core import config as config_module
from raven.core.config import runtime_switches, settings


@pytest.fixture
def switch_names(pin_env_names: Callable[[Iterable[str]], None]) -> None:
    """No switch name this test exports may outlive it."""
    pin_env_names(switch.env_name for switch in runtime_switches())


@pytest.fixture
def switch_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch_names: None) -> Iterator[Path]:
    """Point every switch at a temp env file and put back whatever the test moved.

    `apply_runtime_switch` writes the env file `Settings` obeys, exports the name into the process,
    mutates the settings singleton and rebinds process-wide consumers, so a test that only reads the
    response would still leave the operator's own `.env` edited, the next test answering from the
    value this one set, and the limiter or loguru sinks rebuilt for the rest of the run.
    """
    from raven.core import config_discovery, middleware
    from raven.core.llm import router as router_module

    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_module, "effective_env_file", lambda: path)
    for switch in runtime_switches():
        monkeypatch.setattr(settings, switch.attr, getattr(settings, switch.attr))
    monkeypatch.setattr(middleware, "rate_limiter", middleware.rate_limiter)
    # A credential write rebuilds both cached views of the environment, and each is cached for the
    # whole process: without this the next test answers "OPENAI_API_KEY is not set" from a snapshot
    # taken while this one had the name deleted.
    monkeypatch.setattr(config_discovery, "_discovery_cache", config_discovery._discovery_cache)
    monkeypatch.setattr(router_module, "_default_router", router_module._default_router)
    yield path
