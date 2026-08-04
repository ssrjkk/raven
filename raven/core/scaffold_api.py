from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from raven.core.security.path_guard import confine_path

TEMPLATES: dict[str, dict[str, Any]] = {
    "fastapi-react": {
        "name": "FastAPI + React",
        "description": "Full-stack: Python FastAPI backend + React (Vite) frontend",
        "questions": [
            {"key": "project_name", "label": "Project name", "default": "my-app", "type": "text"},
            {"key": "use_auth", "label": "Include JWT auth?", "default": True, "type": "boolean"},
            {
                "key": "use_db",
                "label": "Database (sqlite/postgres)",
                "default": "sqlite",
                "type": "select",
                "options": ["sqlite", "postgres"],
            },
            {"key": "use_docker", "label": "Add Docker setup?", "default": False, "type": "boolean"},
        ],
        "dirs": [
            "backend/app",
            "backend/app/routes",
            "backend/app/models",
            "frontend/src/components",
            "frontend/src/pages",
        ],
    },
    "python-cli": {
        "name": "Python CLI Tool",
        "description": "Python CLI app with click, logging, and pytest",
        "questions": [
            {"key": "project_name", "label": "Project name", "default": "my-cli", "type": "text"},
            {"key": "use_rich", "label": "Use Rich for pretty CLI?", "default": True, "type": "boolean"},
            {"key": "use_async", "label": "Async support (asyncio)?", "default": False, "type": "boolean"},
        ],
        "dirs": ["src", "src/commands", "tests"],
    },
    "ts-react": {
        "name": "React + TypeScript",
        "description": "React 19 SPA with Vite, Tailwind, Framer Motion",
        "questions": [
            {"key": "project_name", "label": "Project name", "default": "my-react-app", "type": "text"},
            {"key": "use_router", "label": "Include React Router?", "default": True, "type": "boolean"},
            {
                "key": "use_state",
                "label": "State management (none/zustand)",
                "default": "none",
                "type": "select",
                "options": ["none", "zustand"],
            },
        ],
        "dirs": ["src/components", "src/pages", "src/hooks", "src/api"],
    },
    "rust-cli": {
        "name": "Rust CLI",
        "description": "Rust CLI with clap, anyhow, and tracing",
        "questions": [
            {"key": "project_name", "label": "Project name", "default": "my-tool", "type": "text"},
            {"key": "use_serde", "label": "Include serde for serialization?", "default": True, "type": "boolean"},
            {"key": "use_http", "label": "HTTP client (reqwest)?", "default": False, "type": "boolean"},
        ],
        "dirs": ["src", "tests"],
    },
}


class ScaffoldPlan(BaseModel):
    id: str
    name: str
    description: str
    questions: list[dict[str, Any]]


class GenerateRequest(BaseModel):
    template_id: str
    answers: dict[str, Any]
    output_dir: str = ""


class GenerateResponse(BaseModel):
    files: list[dict[str, str]]
    tree: str


def create_scaffold_router(workspace: str = "") -> APIRouter:
    router = APIRouter(prefix="/api/v1/scaffold", tags=["scaffold"])
    ws_root = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    @router.get("/plans")
    def list_plans() -> list[ScaffoldPlan]:
        return [
            ScaffoldPlan(id=tid, name=t["name"], description=t["description"], questions=t["questions"])
            for tid, t in TEMPLATES.items()
        ]

    @router.get("/plans/{template_id}")
    def get_plan(template_id: str) -> ScaffoldPlan:
        t = TEMPLATES.get(template_id)
        if not t:
            raise HTTPException(404, f"Template '{template_id}' not found")
        return ScaffoldPlan(id=template_id, name=t["name"], description=t["description"], questions=t["questions"])

    @router.post("/generate", response_model=GenerateResponse)
    async def generate(req: GenerateRequest) -> GenerateResponse:
        template = TEMPLATES.get(req.template_id)
        if not template:
            raise HTTPException(404, f"Template '{req.template_id}' not found")

        proj_name = req.answers.get("project_name", "my-app")
        target = confine_path(str(ws_root / (req.output_dir or "") / proj_name), ws_root)
        target.mkdir(parents=True, exist_ok=True)

        files: list[dict[str, str]] = []
        for d in template["dirs"]:
            (target / d).mkdir(parents=True, exist_ok=True)

        if req.template_id == "fastapi-react":
            files += _gen_fastapi_react(target, req.answers)
        elif req.template_id == "python-cli":
            files += _gen_python_cli(target, req.answers)
        elif req.template_id == "ts-react":
            files += _gen_ts_react(target, req.answers)
        elif req.template_id == "rust-cli":
            files += _gen_rust_cli(target, req.answers)

        tree = _build_tree(target)
        return GenerateResponse(files=files, tree=tree)

    return router


def _gen_fastapi_react(target: Path, answers: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    pn = answers.get("project_name", "my-app")
    use_auth = answers.get("use_auth", True)
    db = answers.get("use_db", "sqlite")
    use_docker = answers.get("use_docker", False)

    auth_dep = "pyjwt>=2.0\n" if use_auth else ""
    orm_dep = "sqlalchemy>=2.0" if db == "postgres" else "aiosqlite"
    files.append(
        {
            "path": "backend/requirements.txt",
            "content": f"fastapi>=0.110\nuvicorn[standard]\n{orm_dep}\n{auth_dep}python-multipart\n",
        }
    )

    main_py = (
        '"""FastAPI application for ' + pn + '."""\n'
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n\n"
        'app = FastAPI(title="' + pn + '", version="0.1.0")\n\n'
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        '    allow_origins=["http://localhost:5173"],\n'
        "    allow_credentials=True,\n"
        '    allow_methods=["*"],\n'
        '    allow_headers=["*"],\n'
        ")\n\n"
        '@app.get("/api/health")\n'
        "async def health():\n"
        '    return {"status": "ok", "project": "' + pn + '"}\n'
    )
    files.append({"path": "backend/app/main.py", "content": main_py})

    if use_auth:
        auth_py = (
            '"""JWT auth middleware."""\n'
            "from fastapi import Depends, HTTPException, status\n"
            "from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials\n\n"
            "security = HTTPBearer()\n\n"
            "def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:\n"
            "    token = credentials.credentials\n"
            "    if not token:\n"
            "        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)\n"
            "    return token\n"
        )
        files.append({"path": "backend/app/auth.py", "content": auth_py})

    if use_docker:
        files.append(
            {
                "path": "Dockerfile",
                "content": (
                    "FROM python:3.12-slim\n"
                    "WORKDIR /app\n"
                    "COPY backend/requirements.txt .\n"
                    "RUN pip install -r requirements.txt\n"
                    "COPY backend/ .\n"
                    'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
                ),
            }
        )
        files.append(
            {
                "path": "docker-compose.yml",
                "content": (
                    'version: "3.9"\n'
                    "services:\n"
                    "  backend:\n"
                    "    build: .\n"
                    "    ports:\n"
                    '      - "8000:8000"\n'
                    "  frontend:\n"
                    "    image: node:20-alpine\n"
                    "    working_dir: /app\n"
                    "    volumes:\n"
                    "      - ./frontend:/app\n"
                    '    command: sh -c "npm install && npm run dev"\n'
                    "    ports:\n"
                    '      - "5173:5173"\n'
                ),
            }
        )
    return files


def _gen_python_cli(target: Path, answers: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    pn = answers.get("project_name", "my-cli")
    use_rich = answers.get("use_rich", True)
    pkg = pn.replace("-", "_")

    files.append({"path": f"src/{pkg}/__init__.py", "content": f'"""Package: {pn}."""\n'})

    cli_py = (
        '"""CLI entry point for ' + pn + '."""\n'
        "import click\n"
        + ("from rich.console import Console\n\nconsole = Console()\n\n" if use_rich else "\n")
        + "@click.group()\n@click.version_option()\ndef cli():\n"
        + '    """'
        + pn
        + ' - CLI tool."""\n    pass\n\n'
        + '@cli.command()\n@click.argument("name")\ndef hello(name: str):\n'
        + '    """Say hello."""\n'
        + '    msg = f"Hello, {name}!"\n'
        + ("    console.print(msg, style='bold green')\n" if use_rich else "    click.echo(msg)\n")
        + '\nif __name__ == "__main__":\n    cli()\n'
    )
    files.append({"path": f"src/{pkg}/cli.py", "content": cli_py})

    test_py = (
        '"""Tests for ' + pn + '."""\n'
        "from click.testing import CliRunner\n"
        f"from {pkg}.cli import cli\n\n"
        "def test_hello():\n"
        "    runner = CliRunner()\n"
        '    result = runner.invoke(cli, ["hello", "world"])\n'
        "    assert result.exit_code == 0\n"
        '    assert "Hello, world" in result.output\n'
    )
    files.append({"path": "tests/test_cli.py", "content": test_py})

    rich_dep = '\n    "rich>=13.0",' if use_rich else ""
    pyproject = (
        "[build-system]\n"
        'requires = ["setuptools", "wheel"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        f'name = "{pn}"\n'
        'version = "0.1.0"\n'
        f'description = "{pn}"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = [\n"
        '    "click>=8.0",' + rich_dep + "\n"
        "]\n\n"
        "[project.scripts]\n"
        f'{pn} = "{pkg}.cli:cli"\n'
    )
    files.append({"path": "pyproject.toml", "content": pyproject})
    return files


def _gen_ts_react(target: Path, answers: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    pn = answers.get("project_name", "my-react-app")
    use_router = answers.get("use_router", True)
    state_mgmt = answers.get("use_state", "none")

    router_dep = '\n    "react-router-dom": "^7.0.0",' if use_router else ""
    zustand_dep = '\n    "zustand": "^5.0.0"' if state_mgmt == "zustand" else ""

    package_json = (
        "{\n"
        f'  "name": "{pn}",\n'
        '  "private": true,\n'
        '  "version": "0.1.0",\n'
        '  "type": "module",\n'
        '  "scripts": {\n'
        '    "dev": "vite",\n'
        '    "build": "tsc && vite build",\n'
        '    "preview": "vite preview"\n'
        "  },\n"
        '  "dependencies": {\n'
        '    "react": "^19.0.0",\n'
        '    "react-dom": "^19.0.0"' + router_dep + zustand_dep + "\n"
        "  },\n"
        '  "devDependencies": {\n'
        '    "@types/react": "^19.0.0",\n'
        '    "@types/react-dom": "^19.0.0",\n'
        '    "typescript": "^5.5.0",\n'
        '    "vite": "^6.0.0",\n'
        '    "@vitejs/plugin-react": "^4.0.0",\n'
        '    "tailwindcss": "^4.0.0",\n'
        '    "@tailwindcss/vite": "^4.0.0"\n'
        "  }\n"
        "}\n"
    )
    files.append({"path": "package.json", "content": package_json})

    router_import = 'import { BrowserRouter, Routes, Route } from "react-router-dom";\n' if use_router else ""
    app_tsx = (
        'import { useState } from "react";\n' + router_import + "\nexport default function App() {\n"
        "  const [count, setCount] = useState(0);\n"
        "  return (\n"
        '    <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: "#0a0a0a", color: "#e4e4e7" }}>\n'
        '      <div className="text-center space-y-4">\n'
        '        <h1 className="text-3xl font-bold">' + pn + "</h1>\n"
        '        <p className="text-zinc-400">Built with React 19 + Vite</p>\n'
        "        <button onClick={() => setCount(c => c + 1)}\n"
        '          className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium hover:bg-indigo-500">\n'
        "          Count: {count}\n"
        "        </button>\n"
        "      </div>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
    files.append({"path": "src/App.tsx", "content": app_tsx})

    if use_router:
        files.append(
            {
                "path": "src/pages/Home.tsx",
                "content": (
                    'export default function Home() {\n  return <h1 className="text-2xl font-bold">Home</h1>;\n}\n'
                ),
            }
        )
        files.append(
            {
                "path": "src/pages/About.tsx",
                "content": (
                    'export default function About() {\n  return <h1 className="text-2xl font-bold">About</h1>;\n}\n'
                ),
            }
        )

    return files


def _gen_rust_cli(target: Path, answers: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    pn = answers.get("project_name", "my-tool")
    use_serde = answers.get("use_serde", True)
    use_http = answers.get("use_http", False)

    serde_dep = '\nserde = { features = ["derive"], version = "1.0" }' if use_serde else ""
    serde_json_dep = '\nserde_json = "1.0"' if use_serde else ""
    http_dep = '\nreqwest = { features = ["json"], version = "0.12" }' if use_http else ""

    cargo_toml = (
        "[package]\n"
        f'name = "{pn}"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n\n'
        "[dependencies]\n"
        'clap = { features = ["derive"], version = "4.5" }\n'
        'anyhow = "1.0"\n'
        'tracing = "0.1"\n'
        'tracing-subscriber = { features = ["env-filter"], version = "0.3" }'
        + serde_dep
        + serde_json_dep
        + http_dep
        + "\n"
    )
    files.append({"path": "Cargo.toml", "content": cargo_toml})

    main_rs = (
        "use clap::Parser;\n"
        "use anyhow::Result;\n\n"
        "#[derive(Parser)]\n"
        f'#[command(name = "{pn}", version, about = "{pn} CLI")]\n'
        "struct Cli {\n"
        "    /// Name to greet\n"
        "    name: String,\n"
        "}\n\n"
        "#[tokio::main]\n"
        "async fn main() -> Result<()> {\n"
        "    tracing_subscriber::fmt::init();\n"
        "    let cli = Cli::parse();\n"
        '    println!("Hello, {}!", cli.name);\n'
        "    Ok(())\n"
        "}\n"
    )
    files.append({"path": "src/main.rs", "content": main_rs})
    return files


def _build_tree(root: Path) -> str:
    lines: list[str] = []
    root_name = root.name

    def walk(dir: Path, prefix: str = "") -> None:
        entries = sorted(dir.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "\u2502   "
                walk(entry, prefix + extension)

    lines.append(root_name)
    walk(root)
    return "\n".join(lines)
