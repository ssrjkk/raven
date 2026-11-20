from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from raven.core.workspace import workspace_root

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
            "frontend/src/api",
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
    ws_root = Path(workspace).resolve() if workspace else workspace_root()

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
        base = os.path.abspath(str(ws_root))  # noqa: PTH100
        combined = str(ws_root / (req.output_dir or "") / proj_name)
        resolved = os.path.abspath(os.path.normpath(os.path.expanduser(combined)))  # noqa: PTH100, PTH111
        if not resolved.startswith(base):
            raise HTTPException(403, f"Access denied: {req.output_dir}")
        if resolved != base and not resolved.startswith(base + os.sep):
            raise HTTPException(403, f"Access denied: {req.output_dir}")
        target = Path(resolved)

        generators = {
            "fastapi-react": _gen_fastapi_react,
            "python-cli": _gen_python_cli,
            "ts-react": _gen_ts_react,
            "rust-cli": _gen_rust_cli,
        }
        files = generators[req.template_id](req.answers)

        # The page reports "N files created" and prints this tree, so the files have to be on the disk
        # the tree is read from. They were not: the request answered with the file list, created the
        # template's empty directories, and wrote nothing -- the console counted 17 files, showed a
        # skeleton of folders, and left the workspace exactly as it found it.
        clashes = await asyncio.to_thread(_existing_differences, target, files)
        if clashes:
            raise HTTPException(409, f"{proj_name} already holds different content at: {', '.join(clashes)}")

        await asyncio.to_thread(_write_project, target, template["dirs"], files)
        tree = await asyncio.to_thread(_build_tree, target)
        return GenerateResponse(files=files, tree=tree)

    return router


def _write_project(target: Path, dirs: list[str], files: list[dict[str, str]]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (target / d).mkdir(parents=True, exist_ok=True)
    for item in files:
        path = target / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != item["content"]:
            path.write_text(item["content"], encoding="utf-8", newline="\n")


def _existing_differences(target: Path, files: list[dict[str, str]]) -> list[str]:
    """Generated paths that are already on disk with other bytes.

    A scaffold is what a person reaches for when the directory is empty, so a name collision means
    someone's file is in the way. Overwriting it because a template happened to pick the same name --
    `index.html`, `package.json`, `src/App.tsx` -- is the one thing here that cannot be undone, so the
    request stops and says which paths it means.
    """
    clashes: list[str] = []
    for item in files:
        path = target / item["path"]
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace") != item["content"]:
            clashes.append(item["path"])
    return clashes


def _gen_fastapi_react(answers: dict[str, Any]) -> list[dict[str, str]]:
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

    files += _react_starter(pn, "frontend/", use_router=True, state_mgmt="none", with_api=True)
    return files


def _gen_python_cli(answers: dict[str, Any]) -> list[dict[str, str]]:
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


BRAND_TOKENS = r"""/* design-tokens:start - generated by scripts/gen_theme_css.py --print-scaffold, do not edit */
  --dt-colors-bg-primary: #0a0812;
  --dt-colors-bg-secondary: #0d0a16;
  --dt-colors-border-default: rgba(236, 234, 244, 0.08);
  --dt-colors-border-focus: #c4b5fd;
  --dt-colors-accent-default: #8452f5;
  --dt-colors-accent-hover: #7c3aed;
  --dt-colors-accent-active: #6d28d9;
  --dt-colors-accent-muted: rgba(139, 92, 246, 0.15);
  --dt-colors-accent-subtle: rgba(139, 92, 246, 0.10);
  --dt-colors-brand-secondary: #d946ef;
  --dt-colors-surface-card: #161221;
  --dt-colors-surface-elevated: #1a1226;
  --dt-colors-surface-inset-highlight: rgba(236, 234, 244, 0.03);
  --dt-colors-text-primary: #eceaf4;
  --dt-colors-text-secondary: #b4adc6;
  --dt-colors-text-link: #c4b5fd;
  --dt-colors-text-on-accent: #ffffff;
  --dt-colors-status-success: #22c55e;
  --dt-colors-status-warning: #eab308;
  --dt-colors-status-error: #ff6b6b;
  --dt-colors-status-success-bg: rgba(34, 197, 94, 0.1);
  --dt-colors-status-warning-bg: rgba(234, 179, 8, 0.1);
  --dt-colors-status-error-bg: rgba(255, 107, 107, 0.1);
  --dt-typography-font-size-caption: 0.6875rem;
  --dt-typography-font-size-xs: 0.75rem;
  --dt-typography-font-size-sm: 0.875rem;
  --dt-typography-font-size-base: 1rem;
  --dt-typography-line-height-normal: 1.5;
  --dt-animation-duration-fast: 160ms;
  --dt-animation-duration-normal: 320ms;
  --dt-animation-easing-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dt-shadow-glow-accent: 0 2px 12px rgba(139, 92, 246, 0.25);
  --dt-border-radius-sm: 4px;
  --dt-border-radius-md: 6px;
  --dt-border-radius-lg: 8px;
  --dt-border-radius-xl: 12px;
/* design-tokens:end */"""

_FONT_STACK_COMMENT = """  /* Raven sells itself on IBM Plex Sans, IBM Plex Mono and Space Grotesk, and delivers them from
     web/public/fonts as woff2 subsets. A scaffold is a list of text files handed back over HTTP, so
     this project carries no font file and must not name a face it cannot serve: these stacks lead
     with the system tail, which is what the brand families fall through to when they are absent. */"""

_INDEX_CSS_TAIL = """
  --font-body: ui-sans-serif, system-ui, "Segoe UI", sans-serif;
  --font-code: ui-monospace, "Cascadia Mono", Consolas, monospace;
  background: var(--dt-colors-bg-primary);
  color: var(--dt-colors-text-primary);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

body {
  margin: 0;
  font-family: var(--font-body);
  font-size: var(--dt-typography-font-size-sm);
  line-height: var(--dt-typography-line-height-normal);
}

/* The storefront's devices, ported. A generated starter is the first Raven artifact a reader shows a
   colleague, and the recipes here are the SPA sheet's own -- a parity gate compares them byte for byte --
   so the card the scaffold draws is glass over the same two lights and the same grain, not a flat navy
   rectangle. The one deliberate difference is the type: a scaffold is a list of text files handed back
   over HTTP and carries no font file, so the stacks above lead with the system tail. */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: radial-gradient(closest-side at 8% -4%, var(--dt-colors-accent-muted), transparent),
    radial-gradient(closest-side at 96% 4%, var(--dt-colors-accent-subtle), transparent);
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 200px 200px;
}

.screen {
  position: relative;
  z-index: 1;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
}

.column {
  display: grid;
  gap: 0.75rem;
  width: 100%;
  max-width: 32rem;
}

.links {
  display: flex;
  justify-content: center;
  gap: 1rem;
  font-size: var(--dt-typography-font-size-xs);
}

.card {
  position: relative;
  display: grid;
  gap: 0.75rem;
  justify-items: center;
  max-width: 32rem;
  padding: 2.25rem 2rem;
  text-align: center;
  background-image: linear-gradient(135deg, color-mix(in srgb, var(--dt-colors-surface-card) 88%, transparent), color-mix(in srgb, var(--dt-colors-surface-elevated) 72%, transparent));
  border: 1px solid var(--dt-colors-border-default);
  border-radius: var(--dt-border-radius-xl);
  box-shadow: inset 0 1px 0 var(--dt-colors-surface-inset-highlight);
}

/* The wash the storefront lifts its cards off the page with, sized to a card rather than to a window. The
   layer is the sheet's own, painted exactly where every other Raven surface paints it. */
.card::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background-image: radial-gradient(600px 220px at 90% -20%, var(--dt-colors-accent-subtle), transparent 70%);
  pointer-events: none;
}

.eyebrow {
  display: flex;
  align-items: center;
  gap: 0.6em;
  margin: 0;
  font-family: var(--font-code);
  font-size: var(--dt-typography-font-size-caption);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dt-colors-text-link);
}

/* The storefront's kicker: the label is announced by a drawn rule rather than by a bullet. */
.eyebrow::before {
  content: "";
  width: 1.5em;
  height: 1px;
  flex-shrink: 0;
  background: var(--dt-colors-accent-default);
}

.title {
  margin: 0;
  font-size: var(--dt-typography-font-size-base);
  font-weight: 600;
  letter-spacing: -0.01em;
  background-image: linear-gradient(110deg, var(--dt-colors-text-primary) 35%, var(--dt-colors-text-link) 50%, var(--dt-colors-brand-secondary) 62%, var(--dt-colors-text-link) 74%, var(--dt-colors-text-primary) 88%);
  background-size: 250% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: sheen 14s linear infinite;
}

@keyframes sheen {
  from { background-position: 130% 0; }
  to { background-position: -30% 0; }
}

.muted {
  margin: 0;
  color: var(--dt-colors-text-secondary);
}

.status {
  margin: 0;
  padding: 0.3rem 0.7rem;
  font-family: var(--font-code);
  font-size: var(--dt-typography-font-size-xs);
  color: var(--dt-colors-text-secondary);
  background: var(--dt-colors-bg-primary);
  border: 1px solid var(--dt-colors-border-default);
  border-radius: var(--dt-border-radius-md);
}

.status.ok {
  color: var(--dt-colors-status-success);
}

.status.bad {
  color: var(--dt-colors-status-error);
}

.button {
  padding: 0.55rem 1.1rem;
  font: inherit;
  font-weight: 500;
  color: var(--dt-colors-text-on-accent);
  background-image: linear-gradient(135deg, var(--dt-colors-accent-default), var(--dt-colors-accent-active));
  border: 0;
  border-radius: var(--dt-border-radius-sm);
  cursor: pointer;
  transition: filter var(--dt-animation-duration-fast) var(--dt-animation-easing-out), transform var(--dt-animation-duration-fast) var(--dt-animation-easing-out), box-shadow var(--dt-animation-duration-normal) var(--dt-animation-easing-out);
}

.button:hover {
  filter: brightness(1.1);
  box-shadow: var(--dt-shadow-glow-accent);
}

.button:active {
  transform: translateY(1px);
}

.button:focus-visible {
  outline: 2px solid var(--dt-colors-border-focus);
  outline-offset: 2px;
}

a {
  color: var(--dt-colors-text-link);
}

@media (prefers-reduced-motion: reduce) {
  .button {
    transition: none;
  }
  .title {
    animation: none;
  }
}
"""


def _motion_attrs(indent: str) -> str:
    """The one entrance the starter takes: the card lifts 8px into place on the landing's easing.

    `reduce` is framer-motion's `useReducedMotion()`, and `initial={false}` is what makes the card
    appear already in place when the reader has asked for reduced motion -- the same rule the product's
    own surfaces follow.
    """
    inner = indent + "  "
    return (
        inner
        + "initial={reduce ? false : { opacity: 0, y: 8 }}\n"
        + inner
        + "animate={{ opacity: 1, y: 0 }}\n"
        + inner
        + "transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}\n"
        + indent
        + ">\n"
    )


def _react_starter(pn: str, root: str, use_router: bool, state_mgmt: str, with_api: bool) -> list[dict[str, str]]:
    """Every file a Vite React app needs in order to build, painted from the tokens the product uses.

    Both React templates used to hand back four text files and stop: no index.html, no entry module,
    no stylesheet, no tsconfig, no vite config. `npm run dev` answered `Could not resolve entry module
    "index.html"`, and `npm run build` died in `tsc` before it reached Vite, while the frontend tree
    `fastapi-react` created -- `frontend/src/components`, `frontend/src/pages` -- was never given a
    component or a page. What the caller could do with those four files was read them. A generated app
    is a shipped artifact of this product, so it now carries the brand's colour, corners, type ladder
    and one entrance, from the region `--print-scaffold` prints, and it builds.

    The starter's own fonts are the exception the docstring in the stylesheet spells out: a scaffold is
    text over HTTP, so it ships no woff2 and leads its stacks with the system tail rather than promising
    a face it cannot deliver.
    """
    zustand = state_mgmt == "zustand"
    files: list[dict[str, str]] = []

    def add(rel: str, content: str) -> None:
        files.append({"path": f"{root}{rel}", "content": content})

    add(
        "index.html",
        "<!doctype html>\n"
        '<html lang="en" data-theme="dark">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f"    <title>{pn}</title>\n"
        "  </head>\n"
        "  <body>\n"
        '    <div id="root"></div>\n'
        '    <script type="module" src="/src/main.tsx"></script>\n'
        "  </body>\n"
        "</html>\n",
    )

    add(
        "src/index.css",
        '@import "tailwindcss";\n\n:root {\n' + BRAND_TOKENS + "\n" + _FONT_STACK_COMMENT + _INDEX_CSS_TAIL,
    )

    add(
        "src/main.tsx",
        'import "./index.css";\n'
        "\n"
        'import { StrictMode } from "react";\n'
        'import { createRoot } from "react-dom/client";\n'
        "\n"
        'import App from "./App";\n'
        "\n"
        'createRoot(document.getElementById("root")!).render(\n'
        "  <StrictMode>\n"
        "    <App />\n"
        "  </StrictMode>,\n"
        ");\n",
    )

    vite_config = 'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n'
    vite_config += 'import tailwindcss from "@tailwindcss/vite";\n\nexport default defineConfig({\n'
    vite_config += "  plugins: [react(), tailwindcss()],\n  server: {\n    port: 5173,\n"
    if with_api:
        vite_config += '    proxy: {\n      "/api": "http://localhost:8000",\n    },\n'
    vite_config += "  },\n});\n"
    add("vite.config.ts", vite_config)

    add(
        "tsconfig.json",
        "{\n"
        '  "compilerOptions": {\n'
        '    "target": "ES2022",\n'
        '    "lib": ["ES2022", "DOM", "DOM.Iterable"],\n'
        '    "module": "ESNext",\n'
        '    "moduleResolution": "bundler",\n'
        '    "jsx": "react-jsx",\n'
        '    "strict": true,\n'
        '    "noUnusedLocals": true,\n'
        '    "noUnusedParameters": true,\n'
        '    "noFallthroughCasesInSwitch": true,\n'
        '    "verbatimModuleSyntax": true,\n'
        '    "isolatedModules": true,\n'
        '    "skipLibCheck": true,\n'
        '    "noEmit": true,\n'
        '    "types": ["vite/client"]\n'
        "  },\n"
        '  "include": ["src"]\n'
        "}\n",
    )

    add("package.json", _react_package_json(pn, use_router, zustand))
    add(".gitignore", "node_modules/\ndist/\n.env\n*.local\n")

    if zustand:
        add(
            "src/store.ts",
            'import { create } from "zustand";\n'
            "\n"
            "type CounterState = {\n"
            "  count: number;\n"
            "  increment: () => void;\n"
            "};\n"
            "\n"
            "export const useCounter = create<CounterState>((set) => ({\n"
            "  count: 0,\n"
            "  increment: () => set((state) => ({ count: state.count + 1 })),\n"
            "}));\n",
        )

    if with_api:
        add(
            "src/api/health.ts",
            "export type Health = {\n"
            "  status: string;\n"
            "  project: string;\n"
            "};\n"
            "\n"
            "export async function getHealth(): Promise<Health> {\n"
            '  const response = await fetch("/api/health");\n'
            "  if (!response.ok) {\n"
            "    throw new Error(`health answered ${response.status}`);\n"
            "  }\n"
            "  return (await response.json()) as Health;\n"
            "}\n",
        )

    hooks = ["useEffect"] if with_api else []
    if with_api or not zustand:
        hooks.append("useState")
    screen = 'import { motion, useReducedMotion } from "framer-motion";\n'
    if hooks:
        screen += f'import {{ {", ".join([*hooks, "type ReactNode"])} }} from "react";\n'
    else:
        screen += 'import type { ReactNode } from "react";\n'
    screen += "\n"
    if with_api:
        screen += 'import { getHealth } from "../api/health";\nimport type { Health } from "../api/health";\n\n'
    if zustand:
        screen += 'import { useCounter } from "../store";\n\n'
    screen += "type ScreenProps = { children?: ReactNode };\n\n"
    screen += "export default function Screen({ children }: ScreenProps) {\n  const reduce = useReducedMotion();\n"
    if with_api:
        screen += "  const [health, setHealth] = useState<Health | null>(null);\n"
        screen += "  const [unreachable, setUnreachable] = useState(false);\n\n"
        screen += "  useEffect(() => {\n    let active = true;\n    getHealth()\n"
        screen += "      .then((data) => {\n        if (active) setHealth(data);\n      })\n"
        screen += "      .catch(() => {\n        if (active) setUnreachable(true);\n      });\n"
        screen += "    return () => {\n      active = false;\n    };\n  }, []);\n\n"
    if zustand:
        screen += "  const count = useCounter((state) => state.count);\n"
        screen += "  const increment = useCounter((state) => state.increment);\n"
    else:
        screen += "  const [count, setCount] = useState(0);\n"
    click = "increment" if zustand else "() => setCount((value) => value + 1)"
    screen += '\n  return (\n    <main className="screen">\n      <div className="column">\n'
    screen += '        <motion.div\n          className="card"\n'
    screen += _motion_attrs("        ")
    screen += '          <p className="eyebrow">Raven starter</p>\n'
    screen += f'          <h1 className="title">{pn}</h1>\n'
    screen += '          <p className="muted">Edit src/components/Screen.tsx to make this yours.</p>\n'
    screen += f'          <button className="button" type="button" onClick={{{click}}}>Count: {{count}}</button>\n'
    if with_api:
        screen += '          <p className={unreachable ? "status bad" : health ? "status ok" : "status"}>\n'
        screen += (
            "            {unreachable\n"
            '              ? "the backend is not answering on :8000"\n'
            "              : health\n"
            "                ? `backend says ${health.status}`\n"
            '                : "checking the backend…"}\n'
            "          </p>\n"
        )
    screen += "        </motion.div>\n        {children}\n      </div>\n    </main>\n  );\n}\n"
    add("src/components/Screen.tsx", screen)

    if use_router:
        app = 'import { BrowserRouter, Route, Routes } from "react-router-dom";\n\n'
        app += 'import About from "./pages/About";\nimport Home from "./pages/Home";\n\n'
        app += "export default function App() {\n  return (\n    <BrowserRouter>\n      <Routes>\n"
        app += '        <Route path="/" element={<Home />} />\n'
        app += '        <Route path="/about" element={<About />} />\n'
        app += "      </Routes>\n    </BrowserRouter>\n  );\n}\n"
        add("src/App.tsx", app)

        home = 'import { Link } from "react-router-dom";\n'
        home += 'import Screen from "../components/Screen";\n\n'
        home += 'export default function Home() {\n  return (\n    <Screen>\n      <nav className="links">\n'
        home += '        <Link to="/about">About this app</Link>\n'
        home += "      </nav>\n    </Screen>\n  );\n}\n"
        add("src/pages/Home.tsx", home)

        about = 'import { motion, useReducedMotion } from "framer-motion";\n'
        about += 'import { Link } from "react-router-dom";\n\n'
        about += "export default function About() {\n  const reduce = useReducedMotion();\n\n"
        about += '  return (\n    <main className="screen">\n      <motion.section\n        className="card"\n'
        about += _motion_attrs("      ")
        about += f'        <p className="eyebrow">{pn}</p>\n'
        about += '        <h1 className="title">About this app</h1>\n'
        about += '        <p className="muted">This page is a second screen on the same scale, '
        about += "so a new route starts painted rather than unstyled.</p>\n"
        about += '        <Link className="button" to="/">Back to the counter</Link>\n'
        about += "      </motion.section>\n    </main>\n  );\n}\n"
        add("src/pages/About.tsx", about)
    else:
        app = 'import Screen from "./components/Screen";\n\n'
        app += "export default function App() {\n  return <Screen />;\n}\n"
        add("src/App.tsx", app)

    return files


def _react_package_json(pn: str, use_router: bool, zustand: bool) -> str:
    """The dependencies the emitted source actually imports, at the versions the SPA is built against.

    The starter used to pin `vite ^6` and `@vitejs/plugin-react ^4`, which are not the pair this product
    builds with, and it never declared Framer Motion or Tailwind's Vite plugin even though its own
    description promises the first and the plugin is what makes the second reach the stylesheet. A
    package a generated file imports and package.json does not name is an install that builds nothing,
    so the list is derived from the same answers that decide which files are emitted. The health check
    fetches through the dev proxy, so a backend needs no HTTP client of its own.
    """
    deps = ['"react": "^19.3.1"', '"react-dom": "^19.3.1"', '"framer-motion": "^14.10.1"']
    if use_router:
        deps.append('"react-router-dom": "^7.18.5"')
    if zustand:
        deps.append('"zustand": "^5.0.3"')

    dev = [
        '"@types/react": "^19.3.0"',
        '"@types/react-dom": "^19.3.0"',
        '"@vitejs/plugin-react": "^6.2.1"',
        '"@tailwindcss/vite": "^4.3.5"',
        '"tailwindcss": "^4.3.1"',
        '"typescript": "^5.6.0"',
        '"vite": "^8.3.6"',
    ]

    def block(entries: list[str]) -> str:
        return ",\n".join(f"    {entry}" for entry in entries)

    return (
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
        f"{block(deps)}\n"
        "  },\n"
        '  "devDependencies": {\n'
        f"{block(dev)}\n"
        "  }\n"
        "}\n"
    )


def _gen_ts_react(answers: dict[str, Any]) -> list[dict[str, str]]:
    pn = answers.get("project_name", "my-react-app")
    return _react_starter(
        pn,
        "",
        use_router=bool(answers.get("use_router", True)),
        state_mgmt=str(answers.get("use_state", "none")),
        with_api=False,
    )


def _gen_rust_cli(answers: dict[str, Any]) -> list[dict[str, str]]:
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
