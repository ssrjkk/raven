"""A run that asks the Postgres suite to prove something has to hear whether it did.

The gateway could not write a session row on Postgres while the suite that owns that promise reported green:
`pytest -m integration` selected it, no server answered, every case skipped, and a field of skips looks like
a pass in the only line anyone reads. The decision now lives in `tests/integration/conftest.py` — skip a run
that walked past the directory, refuse one that named it — and these tests hold it in both directions,
including one that runs the real pytest against a server that is not there. The gate's own half of the deal is in
`scripts/check_all.py`: it asks the machine whether Postgres answers before it nominates this directory, and where
nothing answers it deselects the cases the `postgres` marker finds -- applied from the `pg_dsn` fixture a case binds,
not from a list of files -- and reports how many it left unproven.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEAD_DSN = "postgresql://nobody:not-a-password@127.0.0.1:1/nothing_listening"


def _conftest() -> Any:
    spec = importlib.util.spec_from_file_location(
        "raven_integration_conftest", ROOT / "tests" / "integration" / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(args: list[str], markexpr: str = "", source: str = "ARGS") -> Any:
    """The three fields the policy reads, and nothing else.

    A stand-in for pytest's own `Config`, which the conftest touches only through `args`, `args_source` and
    `getoption`; the alternative — a real `Config` — is what the subprocess test below builds."""
    return SimpleNamespace(
        args=args,
        args_source=SimpleNamespace(name=source),
        getoption=lambda name, default=None: markexpr if name == "markexpr" else default,
    )


def test_naming_the_suite_by_marker_is_not_a_walk_past() -> None:
    assert _conftest()._suite_selected(_config(["tests"], markexpr="integration")) is True


def test_naming_the_suite_by_path_is_not_a_walk_past() -> None:
    conftest = _conftest()
    assert conftest._suite_selected(_config(["tests/integration/test_postgres_timestamps.py"])) is True
    # The enum member was renamed across pytest versions; both spellings mean "an operator typed this".
    assert conftest._suite_selected(_config(["tests/integration"], source="COMMAND_LINE")) is True
    assert (
        conftest._suite_selected(
            _config(
                [
                    "tests/integration/test_postgres_timestamps.py::test_a_pending_migration_set_leaves_no_naive_columns_anywhere"
                ]
            )
        )
        is True
    )


def test_the_full_suite_walk_past_is_a_walk_past() -> None:
    conftest = _conftest()
    assert conftest._suite_selected(_config(["tests"])) is False
    assert conftest._suite_selected(_config([])) is False
    assert conftest._suite_selected(_config(["tests/core/test_asyncdb.py"])) is False
    # `testpaths` lands in `config.args` the same way a typed path does, so the source is the only thing that
    # tells the full run reaching this directory from an operator asking for it. Measured, not assumed.
    assert conftest._suite_selected(_config(["tests/integration"], source="TESTPATHS")) is False


def test_a_refused_server_fails_the_run_that_asked_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DEAD_DSN)
    with pytest.raises(pytest.fail.Exception, match="selected the Postgres suite"):
        _conftest()._no_backend("Postgres did not answer", _config(["tests/integration"]))


def test_the_same_refusal_only_skips_a_run_that_walked_past(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(pytest.skip.Exception):
        _conftest()._no_backend("Postgres did not answer", _config(["tests"]))


def _collect(*expr: str) -> list[str]:
    """The node ids pytest would run from this directory under `expr`, read off its own collection."""
    env = {
        **os.environ,
        "DATABASE_URL": DEAD_DSN,
        "PYTEST_ADDOPTS": "",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    done = subprocess.run(  # nosec B603  # this repo's interpreter, this repo's files, nothing is connected
        [
            sys.executable,
            "-m",
            "pytest",
            str(ROOT / "tests" / "integration"),
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            *expr,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    return [line.strip() for line in done.stdout.splitlines() if "::" in line]


def test_every_case_that_binds_a_postgres_handle_carries_the_marker() -> None:
    """The gate deselects Postgres cases by marker on a machine with no server, so a case that asks for a
    Postgres handle and is not marked would be nominated there and fail for the missing server. The marker is
    applied from the fixture a case requests, so this reads the collection rather than a list of files."""
    marked = _collect("-m", "postgres")
    assert marked, "no case in tests/integration carries the postgres marker, so the deselection covers nothing"
    assert all(Path(node.split("::", 1)[0]).name.startswith("test_postgres_") for node in marked), marked
    unmarked = _collect("-m", "not postgres")
    assert unmarked, "the Postgres marker deselected the whole directory, so the cases that need no server are gone"
    assert not {node.split("::", 1)[0] for node in marked} & {node.split("::", 1)[0] for node in unmarked}
    assert any(Path(node.split("::", 1)[0]).name == "test_gateway_integration.py" for node in unmarked), (
        "the cases that pass without a server are being deselected with the ones that need one"
    )


def test_pytest_reports_the_refusal_as_a_failing_run() -> None:
    """The policy and the fixture have to agree in a real session: `-m integration` with nothing listening
    exits non-zero and says why, where the same suite reached by an ordinary run still skips quietly."""
    env = {
        **os.environ,
        "DATABASE_URL": DEAD_DSN,
        "PYTEST_ADDOPTS": "",
        # A refused connection comes back in the OS locale, and the child's stdout is inherited by whoever
        # reads it here; without this the decode of a Russian-language socket error is the test failure.
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    one = "test_a_pending_migration_set_leaves_no_naive_columns_anywhere"
    suite = str(ROOT / "tests" / "integration" / "test_postgres_timestamps.py")

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603  # this repo's interpreter, this repo's files, a port nothing listens on
            [sys.executable, "-m", "pytest", *args, "-q", "--no-cov", "-p", "no:cacheprovider", "-k", one],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            text=True,
            timeout=600,
            cwd=str(ROOT),
        )

    selected = _run(suite, "-m", "integration")
    assert selected.returncode != 0, selected.stdout[-2000:] + selected.stderr[-2000:]
    assert "selected the Postgres suite" in selected.stdout, selected.stdout[-2000:]

    typed = _run(suite)
    assert typed.returncode != 0, typed.stdout[-2000:] + typed.stderr[-2000:]
    assert "selected the Postgres suite" in typed.stdout, typed.stdout[-2000:]

    # No positional path: the suite is reached through `testpaths`, the way the full run reaches every file,
    # which is the case that must stay a skip rather than become a wall of red for a developer with no server.
    walked = _run("-o", "testpaths=tests/integration")
    assert walked.returncode == 0, walked.stdout[-2000:] + walked.stderr[-2000:]
    assert "skipped" in walked.stdout and "selected the Postgres suite" not in walked.stdout, walked.stdout[-2000:]
