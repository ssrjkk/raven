from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import ravencode.runtime.skills as skills_mod
from ravencode.runtime.skills import (
    _to_skill,
    discover_skills,
    download_skill,
    get_registry_url,
    get_skill_info,
    list_skills,
    load_skill,
    set_skill_registry,
)


class TestDiscoverSkills:
    def test_discover_returns_dict(self):
        skills = discover_skills()
        assert isinstance(skills, dict)

    def test_discover_includes_builtins(self):
        skills = discover_skills()
        assert "code-review" in skills
        assert "debug" in skills
        assert "test-writer" in skills

    def test_discover_includes_raven_artifacts(self, tmp_path: Path):
        skill_dir = tmp_path / ".raven" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: My custom skill\n---\nDo the thing", encoding="utf-8"
        )
        skills = discover_skills(cwd=tmp_path)
        assert "my-skill" in skills


class TestLoadSkill:
    def test_load_nonexistent(self):
        result = load_skill("nonexistent_skill_xyz")
        assert "not found" in result

    def test_load_builtin(self):
        result = load_skill("security-audit")
        assert "# Skill: Security Audit" in result
        assert "## Instructions" in result
        assert "path injection" in result.lower()

    def test_load_from_raven_layer(self, tmp_path: Path):
        skill_dir = tmp_path / ".raven" / "skills" / "testskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: Test Skill\n---\nDo something useful", encoding="utf-8"
        )
        result = load_skill("testskill", cwd=tmp_path)
        assert "Test Skill" in result
        assert "Do something useful" in result

    def test_load_case_insensitive(self):
        result = load_skill("SECURITY-AUDIT")
        assert "# Skill: Security Audit" in result


class TestListAndInfo:
    def test_list_sorted(self):
        skills = list_skills()
        assert skills == sorted(skills)
        assert "code-review" in skills

    def test_get_info_builtin(self):
        skill = get_skill_info("debug")
        assert skill is not None
        assert skill.name == "Debugging"

    def test_get_info_case_insensitive(self):
        assert get_skill_info("DEBUG") is not None

    def test_get_info_missing(self):
        assert get_skill_info("nope_xyz") is None


class TestToSkill:
    def test_with_examples(self, monkeypatch):
        loaded = SimpleNamespace(
            instructions="ins", examples=["ex1", "ex2"], name="n", description="d", paths=[]
        )
        monkeypatch.setattr("raven.core.artifacts.loader.load_skill", lambda index: loaded)
        skill = _to_skill(object())
        assert skill.name == "n"
        assert skill.description == "d"
        assert skill.instructions == "ins\n\nExamples:\nex1\n\nex2"

    def test_without_examples(self, monkeypatch):
        loaded = SimpleNamespace(instructions="ins", examples=[], name="n", description="d", paths=[Path("a")])
        monkeypatch.setattr("raven.core.artifacts.loader.load_skill", lambda index: loaded)
        skill = _to_skill(object())
        assert skill.instructions == "ins"
        assert skill.paths == [Path("a")]


@pytest.fixture(autouse=True)
def reset_globals() -> Generator[None, None, None]:
    url, builtin = skills_mod._REMOTE_REGISTRY_URL, dict(skills_mod._BUILTIN_SKILLS)
    skills_mod._REMOTE_REGISTRY_URL = ""
    yield
    skills_mod._REMOTE_REGISTRY_URL = url
    skills_mod._BUILTIN_SKILLS.clear()
    skills_mod._BUILTIN_SKILLS.update(builtin)


class _FakeResp:
    def __init__(self, data=None, is_redirect=False, location=None):
        self.data = data
        self.is_redirect = is_redirect
        self._location = location
        self.url = httpx.URL("https://hub.example.com/skills/x")

    @property
    def headers(self):
        return {"Location": self._location} if self._location else {}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.data


class _FakeAsyncClient:
    def __init__(self, resp):
        self._resp = resp
        self.client = MagicMock()
        self.client.get = AsyncMock(return_value=self._resp)

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc) -> bool:
        return False


class TestSetRegistry:
    def test_valid_url(self):
        assert set_skill_registry("https://hub.example.com") == "Registry URL set to: https://hub.example.com"
        assert get_registry_url() == "https://hub.example.com"

    def test_invalid_scheme(self):
        result = set_skill_registry("ftp://hub.example.com")
        assert "invalid registry URL" in result

    def test_no_hostname(self):
        result = set_skill_registry("http://")
        assert "invalid registry URL" in result

    def test_get_registry_default(self):
        assert get_registry_url() == ""


class TestDownloadSkill:
    async def test_no_registry(self):
        assert await download_skill("x") == "[error] no registry URL configured. Use set_skill_registry() first."

    async def test_invalid_skill_id(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        for bad in ("", "a/b", "../x", ".hidden"):
            result = await download_skill(bad)
            assert "invalid skill id" in result

    async def test_ssrf_blocked(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: "private ip")
        assert await download_skill("ok") == "[error] registry URL blocked by SSRF guard: private ip"

    async def test_redirect_blocked(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr(
            "raven.core.security.ssrf.validate_url",
            lambda url: None if url.startswith("https://hub.example.com/skills/") else "bad target",
        )
        resp = _FakeResp(is_redirect=True, location="http://127.0.0.1/evil")
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeAsyncClient(resp))
        result = await download_skill("ok")
        assert result == "[error] registry redirect blocked by SSRF guard: bad target"

    async def test_not_found_404(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: None)
        resp = httpx.Response(404, request=httpx.Request("GET", "https://hub.example.com/skills/x"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeAsyncClient(resp))
        assert await download_skill("x") == "[error] skill 'x' not found in registry"

    async def test_http_error(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: None)
        resp = httpx.Response(500, request=httpx.Request("GET", "https://hub.example.com/skills/x"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeAsyncClient(resp))
        result = await download_skill("x")
        assert "registry request failed" in result

    async def test_no_instructions(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: None)
        resp = _FakeResp(data={"name": "N"})
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeAsyncClient(resp))
        result = await download_skill("x")
        assert "has no instructions in registry" in result

    async def test_success(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: None)
        resp = _FakeResp(data={"name": "My Skill", "description": "D", "instructions": "I"})
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeAsyncClient(resp))
        result = await download_skill("my-skill")
        assert result == "Downloaded and registered skill: My Skill"
        skill = get_skill_info("my-skill")
        assert skill is not None and skill.instructions == "I"

    async def test_generic_exception(self, monkeypatch):
        set_skill_registry("https://hub.example.com")
        monkeypatch.setattr("raven.core.security.ssrf.validate_url", lambda url: None)

        class BoomClient:
            def __init__(self, resp):
                self.client = MagicMock()
                self.client.get = AsyncMock(side_effect=ValueError("boom"))

            async def __aenter__(self):
                return self.client

            async def __aexit__(self, *exc) -> bool:
                return False

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: BoomClient(None))
        result = await download_skill("x")
        assert result == "[error] cannot download skill: boom"
