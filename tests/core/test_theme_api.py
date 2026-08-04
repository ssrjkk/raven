from __future__ import annotations

import json


class TestThemeEndpoints:
    def test_router_registers_theme_endpoints(self):
        from fastapi.routing import APIRoute

        from raven.core.commands_api import create_commands_router

        router = create_commands_router()
        paths = {r.path for r in router.routes if isinstance(r, APIRoute)}
        assert "/api/v1/commands/theme" in paths
        assert "/api/v1/commands/theme/generate" in paths

    def test_get_theme_returns_default(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        response = client.get("/api/v1/commands/theme")
        assert response.status_code == 200
        assert response.json() == {"accentColor": "#7c3aed"}

    def test_save_theme_persists(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        response = client.post("/api/v1/commands/theme", json={"accentColor": "#22c55e"})
        assert response.status_code == 200
        assert response.json() == {"accentColor": "#22c55e"}

        prefs = json.loads((tmp_path / "theme_prefs.json").read_text(encoding="utf-8"))
        assert prefs["accentColor"] == "#22c55e"

        response = client.get("/api/v1/commands/theme")
        assert response.json() == {"accentColor": "#22c55e"}

    def test_save_theme_rejects_invalid_hex(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        response = client.post("/api/v1/commands/theme", json={"accentColor": "purple"})
        assert response.status_code == 400

    def test_generate_theme_deterministic_without_llm(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        response = client.post("/api/v1/commands/theme/generate", json={"prompt": "neon cyberpunk", "use_llm": False})
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "AI · neon cyberpunk"
        assert body["accent"].startswith("#")
        assert "accent" in body["palette"]
        assert "default" in body["palette"]["accent"]
        assert body["accent"] == body["palette"]["accent"]["default"]

    async def test_generate_scheme_same_seed_stable(self):
        from raven.core.commands_api import generate_theme_scheme

        first = await generate_theme_scheme("ocean", seed="fixed-seed", use_llm=False)
        second = await generate_theme_scheme("ocean", seed="fixed-seed", use_llm=False)
        assert first.accent == second.accent
        assert first.palette == second.palette

    async def test_generate_scheme_differs_for_diff_prompts(self):
        from raven.core.commands_api import generate_theme_scheme

        first = await generate_theme_scheme("ocean", use_llm=False)
        second = await generate_theme_scheme("forest", use_llm=False)
        assert first.accent != second.accent

    async def test_generate_scheme_colors_are_valid(self):
        import re

        from raven.core.commands_api import generate_theme_scheme

        scheme = await generate_theme_scheme("magenta vaporwave", use_llm=False)
        hex_re = re.compile(r"^#[0-9a-f]{6}$")
        rgba_re = re.compile(r"^rgba\(\d+, \d+, \d+, (0\.\d+|1)\)$")
        for colors in scheme.palette.values():
            for color in colors.values():
                assert hex_re.fullmatch(color) is not None or rgba_re.fullmatch(color) is not None

    def test_generate_rejects_empty_prompt(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        response = client.post("/api/v1/commands/theme/generate", json={"prompt": "   ", "use_llm": False})
        assert response.status_code == 400

    def test_generate_persists_accent(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from raven.core.commands_api import create_commands_router

        app = FastAPI()
        app.include_router(create_commands_router(data_dir=str(tmp_path)))
        client = TestClient(app)

        client.post("/api/v1/commands/theme/generate", json={"prompt": "coral reef", "use_llm": False})
        response = client.get("/api/v1/commands/theme")
        saved = response.json()["accentColor"]
        assert saved.startswith("#")
        assert saved == client.post(
            "/api/v1/commands/theme/generate", json={"prompt": "coral reef", "use_llm": False}
        ).json()["accent"]
