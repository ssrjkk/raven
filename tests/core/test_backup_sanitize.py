"""The export the security page promises: masked credentials, and a file that refuses restore."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.backup import export_memory, import_memory
from raven.core.dream_api import create_dream_router
from raven.core.memory.base import MemoryTier
from raven.core.memory.manager import MemoryManager
from raven.core.security.credential_masker import MASK, mask_deep, mask_string, name_is_credential


@pytest.fixture
def memory(tmp_path: Path) -> MemoryManager:
    return MemoryManager(workspace=tmp_path)


class TestCredentialMasker:
    def test_provider_shapes_are_masked_inside_prose(self) -> None:
        text = (
            "OPENAI_API_KEY=sk-abcdefghijklmnop1234567890 and a github token "
            "ghp_0123456789abcdefghijABCDEFGHIJ, plus postgres://user:hunter2@db:5432/app"
        )
        masked = mask_string(text)
        assert "sk-abcdefghijklmnop" not in masked
        assert "ghp_0123456789" not in masked
        assert "hunter2" not in masked
        assert masked.count(MASK) == 3

    def test_a_credential_name_masks_the_whole_value(self) -> None:
        assert name_is_credential("OPENAI_API_KEY") is True
        assert name_is_credential("slack-signing-secret") is True
        assert name_is_credential("session_id") is False
        assert name_is_credential("keyboard_layout") is False
        assert mask_deep({"openai_api_key": "not-a-shape-at-all"}) == {"openai_api_key": MASK}

    def test_recursion_covers_lists_and_nested_objects(self) -> None:
        payload = {"notes": ["plain", "token sk-abcdefghijklmnop1234567890"], "nested": {"password": "x"}}
        masked = mask_deep(payload)
        assert masked["notes"][0] == "plain"
        assert MASK in masked["notes"][1]
        assert masked["nested"] == {"password": MASK}

    def test_an_identifier_that_only_looks_long_stays(self) -> None:
        text = "session 7f3d9c1a5b2e4d6f8a0c1b2d3e4f5a6b kept its own id"
        assert mask_string(text) == text


class TestSanitizedExport:
    @pytest.mark.asyncio
    async def test_raw_export_keeps_the_key_the_operator_stored(self, memory: MemoryManager, tmp_path: Path) -> None:
        key = "sk-abcdefghijklmnop1234567890"
        await memory.store("notes/plain", key, tier=MemoryTier.WORKING)
        dest = tmp_path / "raw.json"
        await export_memory(memory, dest=dest)
        assert key in dest.read_text(encoding="utf-8")
        assert "sanitized" not in json.loads(dest.read_text(encoding="utf-8"))

    @pytest.mark.asyncio
    async def test_sanitized_export_hides_it(self, memory: MemoryManager, tmp_path: Path) -> None:
        key = "sk-abcdefghijklmnop1234567890"
        await memory.store("notes/plain", key, tier=MemoryTier.WORKING)
        await memory.store("OPENAI_API_KEY", "whatever-shape-it-has", tier=MemoryTier.LONG_TERM)
        dest = tmp_path / "sanitized.json"
        await export_memory(memory, dest=dest, sanitize=True)
        payload = json.loads(dest.read_text(encoding="utf-8"))
        assert payload["sanitized"] is True
        assert key not in dest.read_text(encoding="utf-8")
        assert "whatever-shape-it-has" not in dest.read_text(encoding="utf-8")
        assert MASK in dest.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_a_sanitized_export_refuses_to_restore(self, memory: MemoryManager, tmp_path: Path) -> None:
        """Restoring masked values would overwrite the real memory with asterisks, so the refusal
        belongs in the importer rather than in a warning nobody reads."""
        dest = tmp_path / "sanitized.json"
        await memory.store("notes/plain", "sk-abcdefghijklmnop1234567890", tier=MemoryTier.WORKING)
        await export_memory(memory, dest=dest, sanitize=True)
        with pytest.raises(ValueError, match="sanitized and cannot be restored"):
            await import_memory(memory, dest)


class TestTheDocumentedCommandExists:
    def test_the_cli_flag_the_page_names_is_real(self) -> None:
        from raven.cli.backup_cmd import backup_group

        result = CliRunner().invoke(backup_group, ["export", "--help"])
        assert result.exit_code == 0, result.output
        assert "--sanitize" in result.output

    def test_every_export_command_the_page_names_exists_in_its_own_cli(self) -> None:
        """A documented flag is only worth what the CLI it names will actually accept."""
        page = (Path(__file__).resolve().parents[2] / "site" / "security.html").read_text(encoding="utf-8")
        assert "<code>raven backup export --sanitize</code>" in page
        assert "<code>ravencode session export --sanitize</code>" in page

        from raven.cli.backup_cmd import backup_group
        from ravencode.cli.main import cli as ravencode_cli

        memory = CliRunner().invoke(backup_group, ["export", "--help"])
        assert "--sanitize" in memory.output, memory.output
        session = CliRunner().invoke(ravencode_cli, ["session", "export", "--help"])
        assert "--sanitize" in session.output, session.output


class TestTheHttpLayerForwardsTheFlag:
    def _client(self, tmp_path: Path) -> tuple[TestClient, AsyncMock]:
        app = FastAPI()
        app.include_router(create_dream_router(MagicMock()))
        return TestClient(app), AsyncMock(return_value=tmp_path / "export.json")

    def test_sanitize_true_reaches_the_exporter(self, tmp_path: Path) -> None:
        client, exporter = self._client(tmp_path)
        with patch("raven.core.backup.export_memory", exporter):
            response = client.post("/api/memory/backup", json={"sanitize": True})
        assert response.status_code == 200, response.text
        assert response.json()["sanitized"] is True
        assert exporter.call_args.kwargs["sanitize"] is True

    def test_a_call_with_no_body_stays_raw(self, tmp_path: Path) -> None:
        client, exporter = self._client(tmp_path)
        with patch("raven.core.backup.export_memory", exporter):
            response = client.post("/api/memory/backup")
        assert response.status_code == 200, response.text
        assert response.json()["sanitized"] is False
        assert exporter.call_args.kwargs["sanitize"] is False
