from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.scaffold_api import (
    TEMPLATES,
    _build_tree,
    _gen_fastapi_react,
    _gen_python_cli,
    _gen_rust_cli,
    _gen_ts_react,
    create_scaffold_router,
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_scaffold_router(workspace=str(tmp_path)))
    return TestClient(app)


def test_list_plans(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(TEMPLATES)
    ids = [p["id"] for p in data]
    assert "fastapi-react" in ids
    assert "python-cli" in ids


def test_get_plan(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans/fastapi-react")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "fastapi-react"
    assert "questions" in data


def test_get_plan_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/scaffold/plans/nonexistent")
    assert resp.status_code == 404


def test_generate_fastapi_react(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "fastapi-react",
            "answers": {"project_name": "test-app", "use_auth": True, "use_db": "sqlite", "use_docker": False},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "tree" in data
    assert len(data["files"]) > 0


def test_generate_python_cli(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "python-cli", "answers": {"project_name": "my-cli", "use_rich": True}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_ts_react(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "ts-react",
            "answers": {"project_name": "my-app", "use_router": True, "use_state": "zustand"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_rust_cli(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "rust-cli", "answers": {"project_name": "my-tool", "use_serde": True, "use_http": False}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) > 0


def test_generate_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "nonexistent", "answers": {}},
    )
    assert resp.status_code == 404


def test_gen_fastapi_react_function() -> None:
    files = _gen_fastapi_react({"project_name": "test", "use_auth": False, "use_db": "sqlite", "use_docker": False})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "backend/requirements.txt" in paths
    assert "backend/app/main.py" in paths


def test_gen_python_cli_function() -> None:
    files = _gen_python_cli({"project_name": "my-cli", "use_rich": False})
    assert len(files) >= 3
    paths = [f["path"] for f in files]
    assert "pyproject.toml" in paths


def test_gen_ts_react_function() -> None:
    files = _gen_ts_react({"project_name": "app", "use_router": False, "use_state": "none"})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "package.json" in paths


def test_gen_rust_cli_function() -> None:
    files = _gen_rust_cli({"project_name": "tool", "use_serde": False, "use_http": False})
    assert len(files) >= 2
    paths = [f["path"] for f in files]
    assert "Cargo.toml" in paths


def test_build_tree(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "file1.txt").write_text("a")
    sub = root / "subdir"
    sub.mkdir()
    (sub / "file2.txt").write_text("b")
    tree = _build_tree(root)
    assert "project" in tree
    assert "file1.txt" in tree
    assert "subdir" in tree
    assert "file2.txt" in tree


# ---------------------------------------------------------------------------------------------
# A generated project is a shipped artifact: it has to build, and the page that reports it has to
# have written it.
#
# Both React templates used to answer with four text files -- a package.json, an App.tsx and two pages
# -- and nothing else. `npm run dev` failed on the missing index.html, `npm run build` failed in `tsc`
# for want of a tsconfig and an entry module, and the only thing the suite asked was `len(files) >= 2`,
# which four unbuildable files satisfy. The helpers below read a generated project the way its build
# does: what the HTML starts from, what each module imports, what each import needs installed.
# ---------------------------------------------------------------------------------------------

_BUILD_INPUTS = ("index.html", "src/main.tsx", "src/index.css", "vite.config.ts", "tsconfig.json", "src/App.tsx")
_IMPORT_SPEC = re.compile(r"""(?:from|import)\s*["']([^"']+)["']""")
_CSS_IMPORT = re.compile(r"""@import\s+["']([^"']+)["']""")
_DOCUMENT_REF = re.compile(r'(?:src|href)="(/[^"]+)"')
_MODULE_SUFFIXES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")

_GENERATORS = {"ts-react": _gen_ts_react, "fastapi-react": _gen_fastapi_react}
REACT_ANSWERS = [
    ("ts-react", {"use_router": True, "use_state": "none"}),
    ("ts-react", {"use_router": True, "use_state": "zustand"}),
    ("ts-react", {"use_router": False, "use_state": "none"}),
    ("ts-react", {"use_router": False, "use_state": "zustand"}),
    ("fastapi-react", {"use_auth": True, "use_db": "postgres", "use_docker": True}),
    ("fastapi-react", {"use_auth": False, "use_db": "sqlite", "use_docker": False}),
]


def _package_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _resolve(emitted: set[str], source: str, spec: str) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(source), spec))
    return next((base + suffix for suffix in _MODULE_SUFFIXES if base + suffix in emitted), None)


def starter_defects(files: list[dict[str, str]]) -> list[str]:
    """Every reason this set of emitted files would not build, as text; empty means it builds."""
    emitted = {f["path"] for f in files}
    content = {f["path"]: f["content"] for f in files}
    roots = sorted({posixpath.dirname(p) or "" for p in emitted if posixpath.basename(p) == "package.json"})
    if not roots:
        return ["no package.json, so nothing declares what the sources import"]

    defects: list[str] = []
    for root in roots:
        manifest_path = f"{root}/package.json" if root else "package.json"
        prefix = f"{root}/" if root else ""
        declared: set[str] = set()
        try:
            manifest = json.loads(content[manifest_path])
        except ValueError as error:
            defects.append(f"{manifest_path} is not valid JSON: {error}")
        else:
            declared = set(manifest.get("dependencies", {})) | set(manifest.get("devDependencies", {}))

        for rel in _BUILD_INPUTS:
            if prefix + rel not in emitted:
                defects.append(f"{prefix}{rel} is where the build starts and is not emitted")

        for path in sorted(p for p in emitted if not prefix or p.startswith(prefix)):
            text = content[path]
            if path.endswith((".ts", ".tsx")):
                for spec in _IMPORT_SPEC.findall(text):
                    if spec.startswith("."):
                        if _resolve(emitted, path, spec) is None:
                            defects.append(f"{path} imports {spec!r}, which resolves to no emitted file")
                    elif _package_name(spec) not in declared:
                        defects.append(f"{path} imports {spec!r}, which {manifest_path} does not declare")
            if path.endswith(".css"):
                for spec in _CSS_IMPORT.findall(text):
                    if _package_name(spec) not in declared:
                        defects.append(f"{path} asks for {spec!r}, which {manifest_path} does not declare")
            if path.endswith(".html"):
                for ref in _DOCUMENT_REF.findall(text):
                    if _resolve(emitted, path, ref.lstrip("/")) is None and prefix + ref.lstrip("/") not in emitted:
                        defects.append(f"{path} starts from {ref}, which is not emitted")
    return defects


@pytest.mark.parametrize(
    "template_id,extra",
    REACT_ANSWERS,
    ids=[
        f"{t}-{e.get('use_state') or e.get('use_db')}-{e.get('use_router', e.get('use_docker'))}"
        for t, e in REACT_ANSWERS
    ],
)
def test_a_generated_react_project_resolves_everything_its_build_needs(
    template_id: str, extra: dict[str, object]
) -> None:
    answers = {"project_name": "starter-check", **extra}
    files = _GENERATORS[template_id](answers)
    assert starter_defects(files) == [], "\n".join(starter_defects(files))


def test_the_build_guard_notices_a_project_that_cannot_be_built() -> None:
    """Each of these is a way the generator has actually been wrong, so the guard is not reading green
    off a project that only ever was fine."""
    files = _gen_ts_react({"project_name": "starter-check", "use_router": True, "use_state": "zustand"})
    assert starter_defects(files) == [], "the shipped generator does not build, so the proofs below mean nothing"

    no_entry = [f for f in files if f["path"] != "index.html"]
    assert any("index.html" in d for d in starter_defects(no_entry)), "dropping the entry file read as a clean project"

    no_screen = [f for f in files if f["path"] != "src/components/Screen.tsx"]
    assert any("Screen" in d for d in starter_defects(no_screen)), (
        "an import of a file the project never emitted passed"
    )

    manifest = next(f for f in files if f["path"] == "package.json")
    data = json.loads(manifest["content"])
    del data["dependencies"]["framer-motion"]
    uninstalled = [{"path": f["path"], "content": json.dumps(data, indent=2)} if f is manifest else f for f in files]
    assert any("framer-motion" in d for d in starter_defects(uninstalled)), (
        "a package the emitted source imports and package.json no longer names read as installable"
    )

    rewritten = [
        {"path": f["path"], "content": f["content"].replace("/src/main.tsx", "/src/entry.tsx")}
        if f["path"] == "index.html"
        else f
        for f in files
    ]
    assert any("entry.tsx" in d for d in starter_defects(rewritten)), (
        "an HTML entry pointing at a module nobody emits read as a project that starts"
    )


def test_generate_writes_the_project_the_page_reports(client: TestClient, tmp_path: Path) -> None:
    """The console counts the files and prints the tree, so the tree has to be what the disk holds.

    `POST /generate` used to create the template's empty directories, return the file list, and write
    none of it: the page said "17 files created", showed a skeleton of folders, and left the workspace
    untouched.
    """
    resp = client.post(
        "/api/v1/scaffold/generate",
        json={
            "template_id": "ts-react",
            "answers": {"project_name": "written-app", "use_router": True, "use_state": "zustand"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    root = tmp_path / "written-app"
    for item in data["files"]:
        on_disk = root / item["path"]
        assert on_disk.is_file(), f"{item['path']} was reported and never written"
        assert on_disk.read_text(encoding="utf-8") == item["content"], item["path"]
    assert "Screen.tsx" in data["tree"], f"the tree names only directories:\n{data['tree']}"


def test_generate_refuses_to_overwrite_a_file_that_is_already_somebody_elses(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "occupied"
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>mine</title>", encoding="utf-8")

    resp = client.post(
        "/api/v1/scaffold/generate",
        json={"template_id": "ts-react", "answers": {"project_name": "occupied", "use_router": False}},
    )
    assert resp.status_code == 409
    assert "index.html" in resp.json()["detail"]
    assert (root / "index.html").read_text(encoding="utf-8") == "<!doctype html><title>mine</title>"
    assert not (root / "src").exists(), "the request wrote part of the project before it refused"


def test_generate_is_idempotent_on_a_project_it_already_wrote(client: TestClient, tmp_path: Path) -> None:
    """A second Generate on the same name is a person fixing an answer, not a collision."""
    body = {"template_id": "ts-react", "answers": {"project_name": "again", "use_router": False}}
    assert client.post("/api/v1/scaffold/generate", json=body).status_code == 200
    again = client.post("/api/v1/scaffold/generate", json=body)
    assert again.status_code == 200, again.json()
