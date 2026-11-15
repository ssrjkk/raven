"""Isolation for the tests that move a runtime switch on a live settings object.

These fixtures are imported by name into the modules that use them rather than served from a
directory ``conftest.py``. pytest 9 resolves a fixture by the identity of the node it was parsed
against (``_pytest.fixtures._matchfactories`` takes the ``baseid`` string only as an ``elif`` to a
failed identity test), and when one run collects both ``tests/core/<file>.py`` and
``tests/test_onboard.py`` the ``tests/core`` package node gets rebuilt -- the conftest's fixture then
names a node that is no longer in the item's parent chain and every test using it dies with
"fixture not found" before it starts. A fixture imported into the test module is parsed against that
module's own node, which is always in the chain.
"""

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
