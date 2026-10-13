from __future__ import annotations

import imaplib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.routine.models import Routine, RoutineAction
from raven.routines import actions


@pytest.mark.asyncio
async def test_execute_briefing_dict_result() -> None:
    provider = AsyncMock(return_value={"content": "Morning all"})
    r = Routine(name="b", action=RoutineAction.SEND_BRIEFING)
    assert await actions.execute_briefing(r, provider) == "Morning all"
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_briefing_plain_string_result() -> None:
    provider = AsyncMock(return_value="plain text")
    r = Routine(name="b", action=RoutineAction.SEND_BRIEFING)
    assert await actions.execute_briefing(r, provider) == "plain text"


@pytest.mark.asyncio
async def test_execute_briefing_falls_back_on_error() -> None:
    provider = AsyncMock(side_effect=RuntimeError("no llm"))
    r = Routine(name="b", action=RoutineAction.SEND_BRIEFING)
    out = await actions.execute_briefing(r, provider)
    assert "Morning Briefing" in out
    assert "operational" in out


@pytest.mark.asyncio
async def test_check_email_gmail_import_error() -> None:
    # raven.integrations.gmail is absent → ImportError branch
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "gmail_api", "credentials_file": "x.json"})
    out = await actions.check_email(r)
    assert out == "[error] gmail integration not installed"


@pytest.mark.asyncio
async def test_check_email_gmail_success(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = types.ModuleType("raven.integrations")
    mod = types.ModuleType("raven.integrations.gmail")
    mod.check_gmail = AsyncMock(return_value="3 unread gmail")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "raven.integrations", pkg)
    monkeypatch.setitem(sys.modules, "raven.integrations.gmail", mod)
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "gmail_api", "credentials_file": "x.json", "max_emails": 2})
    out = await actions.check_email(r)
    assert out == "3 unread gmail"
    mod.check_gmail.assert_awaited_once_with("x.json", max_results=2)


@pytest.mark.asyncio
async def test_check_email_gmail_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = types.ModuleType("raven.integrations")
    mod = types.ModuleType("raven.integrations.gmail")
    mod.check_gmail = AsyncMock(side_effect=RuntimeError("api down"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "raven.integrations", pkg)
    monkeypatch.setitem(sys.modules, "raven.integrations.gmail", mod)
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "gmail_api", "credentials_file": "x.json"})
    out = await actions.check_email(r)
    assert "gmail check failed" in out


@pytest.mark.asyncio
async def test_check_email_imap_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "_imap_check", lambda cfg: "Unread: 4 emails")
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "imap", "server": "imap.x.com"})
    out = await actions.check_email(r)
    assert out == "Unread: 4 emails"


@pytest.mark.asyncio
async def test_check_email_imap_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(cfg: dict[str, object]) -> str:
        raise ConnectionError("socket closed")

    monkeypatch.setattr(actions, "_imap_check", boom)
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "imap", "server": "imap.x.com"})
    out = await actions.check_email(r)
    assert "IMAP check failed" in out


@pytest.mark.asyncio
async def test_check_email_fallback_no_config() -> None:
    r = Routine(name="e", action=RoutineAction.CHECK_EMAIL, config={"provider": "imap"})  # no server
    out = await actions.check_email(r)
    assert "Email check (imap)" in out
    assert "Configure IMAP or Gmail API" in out


@pytest.mark.asyncio
async def test_imap_check_parses_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"From: a@b.com\r\nSubject: Hello\r\nDate: now\r\n\r\n"
    fake_conn = _FakeIMAP(search=("OK", [b"1 2 3"]), fetch=[(b"1 (BODY[HEADER.FIELDS ...])", raw)])
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: fake_conn)
    result = actions._imap_check({"server": "x", "username": "u", "password": "p", "max_emails": 5})
    assert "Unread: 3 emails" in result
    assert "Hello" in result
    assert fake_conn.logged_out


@pytest.mark.asyncio
async def test_imap_check_search_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeIMAP(search=("NO", [b""]), fetch=[])
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: fake_conn)
    result = actions._imap_check({"server": "x"})
    assert result == "[error] IMAP search failed"
    assert fake_conn.logged_out


class _FakeIMAP:
    def __init__(self, search, fetch) -> None:
        self._search = search
        self._fetch = fetch
        self.logged_out = False

    def login(self, *a):
        return ("OK", [b""])

    def select(self, *a):
        return ("OK", [b"1"])

    def search(self, *a):
        return self._search

    def fetch(self, mid, spec):
        # real IMAP returns (status, [ (header_line, raw_bytes), ')' ])
        return ("OK", self._fetch)

    def logout(self):
        self.logged_out = True


@pytest.mark.asyncio
async def test_organize_dry_run_moves_nothing(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("a")
    (tmp_path / "main.py").write_text("b")
    r = Routine(name="o", action=RoutineAction.ORGANIZE_FILES, config={"source_dir": str(tmp_path), "dry_run": True})
    out = await actions.organize_files(r)
    assert "Would organize 2 files" in out
    assert (tmp_path / "note.txt").exists()  # not moved
    assert not (tmp_path / "documents").exists()


@pytest.mark.asyncio
async def test_organize_moves_by_extension(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("a")
    (tmp_path / "main.py").write_text("b")
    (tmp_path / "photo.zzz").write_text("c")  # unknown -> other
    (tmp_path / ".hidden").write_text("d")  # hidden always processed
    (tmp_path / "subdir").mkdir()  # directories skipped
    r = Routine(name="o", action=RoutineAction.ORGANIZE_FILES, config={"source_dir": str(tmp_path)})
    out = await actions.organize_files(r)
    assert "Organized 4 files" in out
    assert (tmp_path / "documents" / "note.txt").exists()
    assert (tmp_path / "code" / "main.py").exists()
    assert (tmp_path / "other" / "photo.zzz").exists()
    assert (tmp_path / "subdir").exists()  # untouched


@pytest.mark.asyncio
async def test_organize_skips_existing_target(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("a")
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "note.txt").write_text("existing")
    r = Routine(name="o", action=RoutineAction.ORGANIZE_FILES, config={"source_dir": str(tmp_path)})
    out = await actions.organize_files(r)
    assert "Organized 0 files" in out
    assert "1 skipped" in out


@pytest.mark.asyncio
async def test_organize_honours_pattern(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("a")
    (tmp_path / "skip.txt").write_text("b")
    r = Routine(name="o", action=RoutineAction.ORGANIZE_FILES, config={"source_dir": str(tmp_path), "pattern": "*.py"})
    out = await actions.organize_files(r)
    assert "Organized 1 files" in out
    assert (tmp_path / "skip.txt").exists()  # not matched by pattern


@pytest.mark.asyncio
async def test_organize_counts_errors_on_move_failure(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("a")
    # a non-matching file named after the target category stays put and blocks mkdir
    (tmp_path / "documents").write_text("I am a file, not a dir")
    r = Routine(
        name="o",
        action=RoutineAction.ORGANIZE_FILES,
        config={"source_dir": str(tmp_path), "pattern": "*.txt"},
    )
    out = await actions.organize_files(r)
    assert "1 errors" in out


@pytest.mark.asyncio
async def test_organize_missing_source_dir(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    r = Routine(name="o", action=RoutineAction.ORGANIZE_FILES, config={"source_dir": str(missing)})
    out = await actions.organize_files(r)
    assert "source directory not found" in out
