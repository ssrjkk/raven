from __future__ import annotations

import contextlib
import os
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

from raven.cli import gateway_runner
from raven.cli.gateway_runner import _server_config, adopt_env_files
from raven.core import config as config_module
from raven.core.asyncdb import is_postgres_url


def test_access_log_is_disabled() -> None:
    """The access log prints the raw request line, and SSE/WebSocket auth travels in ?token=."""
    config = _server_config(FastAPI(), "127.0.0.1", 8000)
    assert isinstance(config, uvicorn.Config)
    assert config.access_log is False
    assert config.ws == "auto"
    assert config.host == "127.0.0.1"
    assert config.port == 8000


@contextlib.contextmanager
def _environment_of_a_fresh_start(*names: str) -> Iterator[None]:
    """Hold the named values out of the process for the block, as a start handed only its files would."""
    taken = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in taken.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestTheGatewayStartAdoptsItsEnvFiles:
    """``Settings`` reads the env files; a reader of ``os.environ`` does not, and nothing adopted them.

    ``DatabaseFactory.create()`` asks the environment for ``DATABASE_URL``, and every channel builds its
    credential from ``os.environ`` in ``__init__``. Measured on 2026-11-14 with the credential in the file
    ``Settings`` had itself just read: a fresh process answered ``configured_channels() == []`` and opened
    the default SQLite path, because there is no ``load_dotenv`` anywhere in this tree — only
    ``ConfigWatcher``, and its reload fires on an edit, never on a start.
    """

    def test_a_name_only_the_file_holds_is_in_the_environment(self, tmp_path: Path, monkeypatch) -> None:
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=postgresql://raven:pass@127.0.0.1:5432/raven\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(env)])
        with _environment_of_a_fresh_start("DATABASE_URL"):
            assert not is_postgres_url(os.environ.get("DATABASE_URL", ""))
            assert adopt_env_files() == ["DATABASE_URL"]
            assert is_postgres_url(os.environ["DATABASE_URL"])

    def test_what_the_operator_exported_beats_the_file(self, tmp_path: Path, monkeypatch) -> None:
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=postgresql://from/the/file@127.0.0.1/raven\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(env)])
        monkeypatch.setenv("DATABASE_URL", "postgresql://from/the/shell@127.0.0.1/raven")
        assert adopt_env_files() == []
        assert os.environ["DATABASE_URL"] == "postgresql://from/the/shell@127.0.0.1/raven"

    def test_the_database_is_built_after_the_adoption(self, tmp_path: Path, monkeypatch) -> None:
        """Ordering, proved by the reader's own answer rather than by where a call sits in the source.

        Every start path — ``raven start``, the Windows service, ``raven plugins`` — reaches the process
        through ``create_gateway``, so what the factory sees here is what the shipped gateway sees.
        """
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=postgresql://sentinel@127.0.0.1:5432/raven\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(env)])

        seen: list[str | None] = []

        class _StopBuildError(RuntimeError):
            pass

        def _fake_create() -> None:
            seen.append(os.environ.get("DATABASE_URL"))
            raise _StopBuildError

        monkeypatch.setattr(gateway_runner, "DatabaseFactory", types.SimpleNamespace(create=_fake_create))
        with _environment_of_a_fresh_start("DATABASE_URL"):
            with pytest.raises(_StopBuildError):
                gateway_runner.create_gateway()
        assert seen == ["postgresql://sentinel@127.0.0.1:5432/raven"]
