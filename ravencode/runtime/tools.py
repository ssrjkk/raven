from __future__ import annotations

import asyncio
import contextvars
import difflib
import fnmatch
import functools
import hashlib
import json
import os
import shlex
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.agents.validation import validate_tool_arguments
from raven.core.security.ssrf import safe_fetch_async, validate_url
from ravencode.core.metrics import observe_tool
from ravencode.runtime.question import QuestionError
from ravencode.runtime.undo import get_undo_manager

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_workspace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("_workspace_var", default=None)


def _get_workspace() -> Path:
    override = _workspace_var.get()
    root = override if override is not None else os.environ.get("RAVEN_WORKSPACE", "workspace")
    return Path(root).expanduser().resolve()


def set_workspace_root(root: str | Path) -> None:
    _workspace_var.set(str(root))


def _confine(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    ws = _get_workspace()
    try:
        p.relative_to(ws)
    except ValueError as exc:
        msg = f"Path {path} is outside workspace {ws}"
        raise PermissionError(msg) from exc
    return p


def _compute_diff(original: str, modified: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )


async def _safe_read(path: str, max_chars: int = 50_000) -> tuple[str, str]:
    p = _confine(path)
    if not p.is_file():
        return "", f"[error] file not found: {path}"
    try:
        content = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
    except Exception as exc:
        return "", f"[error] cannot read {path}: {exc}"
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n... (truncated, {len(content)} total chars)"
    return content, ""


async def _safe_write(path: str, content: str) -> None:
    p = _confine(path)
    if p.is_file():
        original = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
        get_undo_manager().record(str(p), original, content, "write")
    else:
        get_undo_manager().record(str(p), "", content, "write")
    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


async def read_file(path: str, max_chars: int = 50_000) -> str:
    content, err = await _safe_read(path, max_chars)
    return err or content


async def write_file(path: str, content: str) -> str:
    try:
        await _safe_write(path, content)
        return f"[ok] wrote {len(content)} chars to {path}"
    except PermissionError as exc:
        return f"[error] {exc}"


async def edit_file(path: str, old_string: str, new_string: str, preview: bool = False) -> str:
    content, err = await _safe_read(path)
    if err:
        return err
    if old_string not in content:
        return f"[error] old_string not found in {path}"
    count = content.count(old_string)
    if count > 1:
        return f"[error] found {count} occurrences — provide more context"
    new_content = content.replace(old_string, new_string, 1)
    if preview:
        return f"[diff for {path}]\n{_compute_diff(content, new_content, path)}"
    get_undo_manager().record(str(_confine(path)), content, new_content, "edit")
    try:
        await _safe_write(path, new_content)
        return f"[ok] applied edit to {path}"
    except PermissionError as exc:
        return f"[error] {exc}"


async def glob_files(pattern: str, path: str | None = None) -> list[str]:
    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [f"[error] directory not found: {path or search_root}"]
    results = []
    for p in search_root.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(str(p.relative_to(search_root)), pattern):
            results.append(str(p.relative_to(search_root)))
    return sorted(results)[:500]


async def grep_files(pattern: str, include: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [{"error": f"directory not found: {path or search_root}"}]
    results = []
    for p in search_root.rglob("*"):
        if not p.is_file():
            continue
        if include and not fnmatch.fnmatch(p.name, include):
            continue
        try:
            text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("Skipping unreadable file {}: {}", p, e)
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern in line:
                results.append({"file": str(p.relative_to(search_root)), "line": i, "content": line[:200]})
                if len(results) >= 200:
                    return results
    return results


_BASH_ALLOWLIST = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "echo",
        "pwd",
        "whoami",
        "date",
        "find",
        "grep",
        "rg",
        "wc",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "curl",
        "wget",
        "df",
        "du",
        "free",
        "ps",
        "top",
        "uptime",
        "git",
        "make",
        "npm",
        "pip",
        "go",
        "rustc",
        "cargo",
        "python",
        "python3",
        "node",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "chmod",
        "touch",
        "docker",
        "kubectl",
        "which",
        "type",
        "env",
        "npx",
        "pwsh",
        "powershell",
    }
)


async def bash_exec(command: str, timeout: int = 30) -> str:
    parts = shlex.split(command)
    if not parts:
        return "[error] empty command"
    cmd_base = Path(parts[0]).name
    if cmd_base not in _BASH_ALLOWLIST:
        return f"[denied] command '{cmd_base}' not in allowlist"
    proc = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:30_000]
    if stderr:
        output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


async def _ddg_search(query: str, num_results: int) -> list[dict[str, str]] | None:
    try:
        from duckduckgo_search import DDGS

        def _search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=num_results))

        results = await asyncio.to_thread(_search)
        return results if results else None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("DDG search failed: {}, trying fallback", e)
        return None


async def _httpx_search(query: str, num_results: int) -> list[dict[str, str]] | None:
    try:
        import httpx
        from bs4 import BeautifulSoup

        url = f"https://html.duckduckgo.com/html/?q={_urlencode(query)}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for i, link in enumerate(soup.select("a.result__a")):
            if i >= num_results:
                break
            title = str(link.get_text(strip=True))
            href_attr = link.get("href", "")
            href = str(href_attr) if href_attr else ""
            body_el = link.find_next("a", class_="result__snippet")
            body = str(body_el.get_text(strip=True)) if body_el else ""
            results.append({"title": title, "href": href, "body": body})
        return results if results else None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("httpx search fallback failed: {}", e)
        return None


def _urlencode(q: str) -> str:
    import urllib.parse

    return urllib.parse.quote(q)


async def web_search(query: str, num_results: int = 5) -> str:
    results = await _ddg_search(query, num_results) or await _httpx_search(query, num_results)
    if not results:
        return "(no results)"
    return "\n\n".join(f"• {r.get('title', '')}\n  {r.get('body', '')[:200]}\n  {r.get('href', '')}" for r in results)


async def web_fetch(url: str) -> str:
    if not validate_url(url):
        return f"[denied] URL blocked by SSRF guard: {url}"
    try:
        resp = await safe_fetch_async(url, timeout=30.0, headers={"User-Agent": "Raven/1.0"})
        resp.raise_for_status()
        return resp.text[:50_000]
    except ValueError as exc:
        logger.warning("web_fetch blocked: {}", exc)
        return f"[denied] URL blocked by SSRF guard: {exc}"
    except Exception as exc:
        logger.exception("web_fetch failed")
        return f"[error] web_fetch: {exc}"


async def think(reasoning: str) -> str:
    return f"[thinking: {reasoning}]"


_task_depth: contextvars.ContextVar[int] = contextvars.ContextVar("_task_depth", default=0)
_MAX_TASK_DEPTH = 5
_AGENT_MEMORY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("_AGENT_MEMORY", default=None)


def set_agent_memory(memory: dict[str, Any] | None) -> None:
    _AGENT_MEMORY.set(memory)


async def task_delegate(description: str, context: str | None = None) -> str:
    depth = _task_depth.get()
    if depth >= _MAX_TASK_DEPTH:
        return f"[error] max task delegation depth ({_MAX_TASK_DEPTH}) exceeded"
    token = _task_depth.set(depth + 1)
    try:
        from ravencode.core.prompts import get_prompt
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent
        from ravencode.runtime.context import Conversation

        parent_memory = _AGENT_MEMORY.get()
        sub_prompt = get_prompt("delegate")
        if context:
            sub_prompt += f"\nContext from parent:\n{context}"
        if parent_memory:
            sub_prompt += f"\nParent session context:\n{parent_memory}"
        prompt = f"{sub_prompt}\n\nTask: {description}"
        sub = ReActAgent(config=AgentConfig(max_steps=15), conversation=Conversation(system_prompt=sub_prompt))
        return await sub.run(prompt)
    finally:
        _task_depth.reset(token)


# ---------------------------------------------------------------------------
# git tools
# ---------------------------------------------------------------------------


async def _git_cmd(*args: str, cwd: str | None = None) -> str:
    cmd = ["git", *list(args)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            logger.debug("git process already exited during timeout kill")
        return "[timeout]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:20_000]
    if stderr:
        output += "\n" + stderr.decode("utf-8", errors="replace")[:5_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output


async def git_status(path: str | None = None) -> str:
    return await _git_cmd("status", cwd=path)


async def git_diff(path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--cached"] if staged else ["diff"]
    return await _git_cmd(*args, cwd=path)


async def git_log(max_count: int = 10, path: str | None = None) -> str:
    return await _git_cmd("log", f"--max-count={max_count}", "--oneline", cwd=path)


async def git_commit(message: str, path: str | None = None) -> str:
    return await _git_cmd("commit", "-m", message, cwd=path)


async def git_add(files: str, path: str | None = None) -> str:
    return await _git_cmd("add", *files.split(), cwd=path)


# ---------------------------------------------------------------------------
# image / multimodal
# ---------------------------------------------------------------------------


async def read_image(path: str) -> str:
    try:
        p = _confine(path)
    except PermissionError as exc:
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    ext = p.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"):
        return f"[error] unsupported image format: {ext}"
    import base64

    raw = await asyncio.to_thread(p.read_bytes)
    size = await asyncio.to_thread(p.stat)
    data = base64.b64encode(raw[:500_000]).decode("ascii")
    return f"Image ({size.st_size} bytes, {ext}): data:image/{ext[1:]};base64,{data}"


# ---------------------------------------------------------------------------
# artifact creation
# ---------------------------------------------------------------------------


async def create_artifact(title: str, artifact_type: str, content: str, path: str | None = None) -> str:
    """Create an interactive artifact and persist it to the workspace when possible."""
    try:
        ws = _get_workspace()
        file_path: str | None = None
        if path and artifact_type in ("react", "html", "python", "markdown", "typescript", "javascript"):
            try:
                target = Path(path).expanduser() if Path(path).is_absolute() else ws / path
                safe_path = _confine(str(target))
            except PermissionError as exc:
                return json.dumps({"error": f"Path confinement failed: {exc}"}, ensure_ascii=False)
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(safe_path.write_text, content, encoding="utf-8")
            file_path = str(safe_path.relative_to(ws))
        artifact_id = hashlib.sha256(f"{title}:{content[:50]}".encode()).hexdigest()[:8]
        return json.dumps(
            {
                "artifact_id": artifact_id,
                "title": title,
                "type": artifact_type,
                "content": content,
                "file_path": file_path,
                "status": "created",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": f"create_artifact failed: {exc}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# undo / redo tools
# ---------------------------------------------------------------------------


async def undo_action() -> str:
    result = await asyncio.to_thread(get_undo_manager().undo)
    return result or "[undo] nothing to undo"


async def redo_action() -> str:
    result = await asyncio.to_thread(get_undo_manager().redo)
    return result or "[redo] nothing to redo"


# ---------------------------------------------------------------------------
# checkpoint tools
# ---------------------------------------------------------------------------


async def checkpoint_save_tool(description: str = "") -> str:
    from ravencode.runtime.checkpoints import get_checkpoint_manager

    return await get_checkpoint_manager().save(description)


async def checkpoint_restore_tool(cid: str) -> str:
    from ravencode.runtime.checkpoints import get_checkpoint_manager

    return await get_checkpoint_manager().restore(cid)


async def checkpoint_list_tool() -> str:
    from ravencode.runtime.checkpoints import get_checkpoint_manager

    cps = await asyncio.to_thread(get_checkpoint_manager().list)
    if not cps:
        return "(no checkpoints)"
    return "\n".join(f"{cp['id']}: {cp['description']} ({cp['created']})" for cp in cps)


# ---------------------------------------------------------------------------
# LSP tools
# ---------------------------------------------------------------------------


async def lsp_completion_tool(path: str, line: int, col: int) -> str:
    from ravencode.runtime.lsp import lsp_completion

    return await lsp_completion(path, line, col)


async def lsp_definition_tool(path: str, line: int, col: int) -> str:
    from ravencode.runtime.lsp import lsp_definition

    return await lsp_definition(path, line, col)


async def lsp_references_tool(path: str, line: int, col: int) -> str:
    from ravencode.runtime.lsp import lsp_references

    return await lsp_references(path, line, col)


async def lsp_hover_tool(path: str, line: int, col: int) -> str:
    from ravencode.runtime.lsp import lsp_hover

    return await lsp_hover(path, line, col)


# ---------------------------------------------------------------------------
# sandbox tools
# ---------------------------------------------------------------------------


async def sandbox_exec_tool(code: str, language: str = "python") -> str:
    from ravencode.runtime.sandbox import get_sandbox

    return await get_sandbox().run_code(code, language)


# ---------------------------------------------------------------------------
# smart diff tools
# ---------------------------------------------------------------------------


async def smart_edit_tool(
    path: str,
    old_text: str | None = None,
    new_text: str | None = None,
    insert_after: str | None = None,
    insert_before: str | None = None,
    append: bool = False,
) -> str:
    from ravencode.runtime.diff import smart_edit

    return await asyncio.to_thread(
        smart_edit,
        path,
        old_text=old_text,
        new_text=new_text,
        insert_after=insert_after,
        insert_before=insert_before,
        append=append,
    )


async def patch_file_tool(path: str, diff_text: str) -> str:
    from ravencode.runtime.diff import apply_patch

    return await asyncio.to_thread(apply_patch, path, diff_text)


# ---------------------------------------------------------------------------
# auto-format tools
# ---------------------------------------------------------------------------


async def format_file_tool(path: str) -> str:
    from ravencode.runtime.formatters import format_file

    return await format_file(path)


async def format_files_tool(paths: list[str]) -> str:
    from ravencode.runtime.formatters import format_files

    return await format_files(paths)


# ---------------------------------------------------------------------------
# auto-git tools
# ---------------------------------------------------------------------------


async def auto_commit_tool(message: str | None = None, path: str | None = None) -> str:
    from ravencode.runtime.autogit import auto_commit

    return await auto_commit(path=path, message=message)


async def load_skill(name: str) -> str:
    from ravencode.runtime.skills import load_skill as _load_skill

    return _load_skill(name)


async def download_skill(name: str) -> str:
    from ravencode.runtime.skills import download_skill as _download_skill

    return await _download_skill(name)


async def set_skill_registry(url: str) -> str:
    from ravencode.runtime.skills import set_skill_registry as _set_registry

    return _set_registry(url)


async def todo_write(tasks: list[dict[str, str]]) -> str:
    from ravencode.runtime.todo import todo_write as _todo_write

    return _todo_write(tasks)


async def todo_list(status_filter: str | None = None) -> str:
    from ravencode.runtime.todo import todo_list as _todo_list

    return _todo_list(status_filter)


async def todo_update(tid: str, status: str) -> str:
    from ravencode.runtime.todo import todo_update as _todo_update

    return _todo_update(tid, status)


async def todo_clear() -> str:
    from ravencode.runtime.todo import todo_clear as _todo_clear

    _todo_clear()
    return "(todo list cleared)"


async def question_tool(
    question: str,
    header: str = "",
    options: list[dict[str, str]] | None = None,
    multiple: bool = False,
) -> str:
    from ravencode.runtime.question import Question, ask_question

    q = Question(
        question=question,
        header=header,
        options=options or [],
        multiple=multiple,
    )
    return await ask_question(q)


async def anchored_summary_read() -> str:
    from ravencode.runtime.anchored import anchored_summary

    val = anchored_summary()
    return val if val else "(no anchored summary)"


async def anchored_summary_write(text: str) -> str:
    from ravencode.runtime.anchored import update_anchored_summary

    return update_anchored_summary(text)


async def anchored_summary_append(text: str) -> str:
    from ravencode.runtime.anchored import append_anchored_summary

    return append_anchored_summary(text)


async def anchored_summary_clear() -> str:
    from ravencode.runtime.anchored import clear_anchored_summary

    return clear_anchored_summary()


async def browser_navigate(url: str) -> str:
    from ravencode.runtime.browser import browser_navigate as _navigate

    return await _navigate(url)


async def browser_click(selector: str) -> str:
    from ravencode.runtime.browser import browser_click as _click

    return await _click(selector)


async def browser_type(selector: str, text: str) -> str:
    from ravencode.runtime.browser import browser_type as _type

    return await _type(selector, text)


async def browser_screenshot(path: str = "screenshot.png") -> str:
    from ravencode.runtime.browser import browser_screenshot as _screenshot

    return await _screenshot(path)


async def browser_get_html(selector: str = "body") -> str:
    from ravencode.runtime.browser import browser_get_html as _get_html

    return await _get_html(selector)


async def browser_evaluate(script: str) -> str:
    from ravencode.runtime.browser import browser_evaluate as _evaluate

    return await _evaluate(script)


async def browser_close() -> str:
    from ravencode.runtime.browser import browser_close as _close

    return await _close()


# ---------------------------------------------------------------------------
# RavenFlow tools
# ---------------------------------------------------------------------------


async def _canvas_render_handler(components: list[dict[str, Any]]) -> str:
    rendered = []
    for comp in components:
        ctype = comp.get("type", "text")
        content = comp.get("content", "")
        if ctype == "code":
            lang = comp.get("language", "")
            rendered.append(f"```{lang}\n{content}\n```")
        elif ctype == "table":
            headers = comp.get("headers", [])
            rows = comp.get("rows", [])
            rendered.append(
                " | ".join(headers)
                + "\n"
                + " | ".join(["---"] * len(headers))
                + "\n"
                + "\n".join(" | ".join(str(c) for c in row) for row in rows)
            )
        elif ctype == "mermaid":
            rendered.append(f"```mermaid\n{content}\n```")
        elif ctype == "alert":
            level = comp.get("level", "info")
            rendered.append(f"> [!{level.upper()}]\n> {content}")
        elif ctype == "list":
            items = comp.get("items", [])
            rendered.append("\n".join(f"- {i}" for i in items))
        else:
            rendered.append(content)
    return "\n\n".join(rendered)


async def _nodes_list_handler() -> str:
    try:
        from raven.tools.nodes import nodes_list

        return await nodes_list()
    except ImportError:
        return "(nodes module not available)"


async def _cron_schedule_handler(cron: str, task: str, task_id: str | None = None) -> str:
    try:
        from raven.plugins.cron.plugin import schedule

        return await schedule(cron, task, task_id)
    except ImportError:
        return "[error] cron plugin not available"


async def _cron_list_handler() -> str:
    try:
        from raven.plugins.cron.plugin import list_schedules

        return await list_schedules()
    except ImportError:
        return "(cron plugin not available)"


async def _cron_cancel_handler(task_id: str) -> str:
    try:
        from raven.plugins.cron.plugin import cancel_schedule

        return await cancel_schedule(task_id)
    except ImportError:
        return "[error] cron plugin not available"


_current_sandbox_policy: str = "main"


async def _sandbox_policy_handler(policy: str | None = None) -> str:
    global _current_sandbox_policy
    if policy:
        valid = {"main", "non-main", "code-exec", "web-browsing", "read-only"}
        if policy not in valid:
            return f"[error] unknown policy: {policy}. Available: {', '.join(sorted(valid))}"
        _current_sandbox_policy = policy
        return f"Sandbox policy set to: {policy}"
    return f"Current sandbox policy: {_current_sandbox_policy}"


async def _talk_handler(text: str, voice: str = "", provider: str = "") -> str:
    from raven.voice.tts import TextToSpeech, TTSConfig, TTSProvider

    try:
        prov = TTSProvider(provider) if provider else TTSProvider.SYSTEM
    except ValueError:
        prov = TTSProvider.SYSTEM
    config = TTSConfig(provider=prov, voice=voice)
    tts = TextToSpeech(config)
    path = await asyncio.to_thread(tts.synthesize, text)
    return f"Audio saved to {path}"


# ---------------------------------------------------------------------------
# tool registry
# ---------------------------------------------------------------------------

MODULE_TOOLS: dict[str, dict[str, Any]] = {
    "read": {
        "name": "read",
        "dangerous": False,
        "description": "Read the contents of a file. Returns up to 50,000 characters.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "max_chars": {
                    "type": "integer",
                    "description": "Max chars to return (default 50000)",
                    "default": 50000,
                },
            },
            "required": ["path"],
        },
        "handler": read_file,
    },
    "write": {
        "name": "write",
        "dangerous": True,
        "description": "Write content to a file (overwrites existing). Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
    },
    "edit": {
        "name": "edit",
        "dangerous": True,
        "description": "Edit a file by finding and replacing text. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "old_string": {"type": "string", "description": "Text to find (must be unique)"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "preview": {"type": "boolean", "description": "Show diff without applying", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file,
    },
    "glob": {
        "name": "glob",
        "dangerous": False,
        "description": "Search for files matching a glob pattern. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.ts')"},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": glob_files,
    },
    "grep": {
        "name": "grep",
        "dangerous": False,
        "description": "Search file contents for a string pattern. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text to search for"},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": None},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": grep_files,
    },
    "bash": {
        "name": "bash",
        "dangerous": True,
        "description": "Execute a shell command from the allowlist. Supports quoted arguments.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            },
            "required": ["command"],
        },
        "handler": bash_exec,
    },
    "web_search": {
        "name": "web_search",
        "dangerous": False,
        "description": "Search the web for current information (DuckDuckGo).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        "handler": web_search,
    },
    "web_fetch": {
        "name": "web_fetch",
        "dangerous": False,
        "description": "Fetch URL contents. SSRF-guarded against private IP ranges.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        "handler": web_fetch,
    },
    "think": {
        "name": "think",
        "dangerous": False,
        "description": "Use this tool to reason about the problem before taking action. No external effect.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "description": "Your step-by-step reasoning"},
            },
            "required": ["reasoning"],
        },
        "handler": think,
    },
    "task": {
        "name": "task",
        "dangerous": False,
        "description": "Delegate a sub-task to a new agent (max depth 5). Use for parallel work.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Task description for the sub-agent"},
                "context": {"type": "string", "description": "Optional context to pass", "default": None},
            },
            "required": ["description"],
        },
        "handler": task_delegate,
    },
    "git_status": {
        "name": "git_status",
        "dangerous": False,
        "description": "Show git working tree status.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_status,
    },
    "git_diff": {
        "name": "git_diff",
        "dangerous": False,
        "description": "Show git diff of unstaged changes, or staged changes with staged=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
                "staged": {"type": "boolean", "description": "Show staged diff instead", "default": False},
            },
            "required": [],
        },
        "handler": git_diff,
    },
    "git_log": {
        "name": "git_log",
        "dangerous": False,
        "description": "Show recent git commit history (one-line format).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "description": "Number of commits (default 10)", "default": 10},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_log,
    },
    "git_commit": {
        "name": "git_commit",
        "dangerous": True,
        "description": "Create a git commit with the given message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["message"],
        },
        "handler": git_commit,
    },
    "git_add": {
        "name": "git_add",
        "dangerous": True,
        "description": "Stage files for commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {"type": "string", "description": "Files to stage (space-separated)"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["files"],
        },
        "handler": git_add,
    },
    "read_image": {
        "name": "read_image",
        "dangerous": False,
        "description": "Read an image file (png, jpg, gif, webp, svg) confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
            },
            "required": ["path"],
        },
        "handler": read_image,
    },
    "create_artifact": {
        "name": "create_artifact",
        "dangerous": False,
        "description": (
            "Create an interactive artifact (React component, HTML page, Mermaid diagram or SVG). "
            "Use this instead of dumping large code blocks into the chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short artifact title, e.g. 'Login Form'"},
                "artifact_type": {
                    "type": "string",
                    "enum": ["react", "html", "mermaid", "svg", "markdown", "python", "typescript"],
                    "description": "Content type for frontend rendering",
                },
                "content": {"type": "string", "description": "Full source code or artifact content"},
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative path to persist the artifact as a file",
                },
            },
            "required": ["title", "artifact_type", "content"],
        },
        "handler": create_artifact,
    },
    "undo": {
        "name": "undo",
        "dangerous": False,
        "description": "Undo the last file write or edit operation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": undo_action,
    },
    "redo": {
        "name": "redo",
        "dangerous": False,
        "description": "Redo the last undone file operation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": redo_action,
    },
    "checkpoint_save": {
        "name": "checkpoint_save",
        "dangerous": False,
        "description": "Save a snapshot of the workspace as a restore point.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Optional description", "default": ""},
            },
            "required": [],
        },
        "handler": checkpoint_save_tool,
    },
    "checkpoint_restore": {
        "name": "checkpoint_restore",
        "dangerous": True,
        "description": "Restore workspace files from a saved checkpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "cid": {"type": "string", "description": "Checkpoint ID"},
            },
            "required": ["cid"],
        },
        "handler": checkpoint_restore_tool,
    },
    "checkpoint_list": {
        "name": "checkpoint_list",
        "dangerous": False,
        "description": "List all saved checkpoints.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": checkpoint_list_tool,
    },
    "lsp_completion": {
        "name": "lsp_completion",
        "dangerous": False,
        "description": "Get code completion suggestions via LSP at a given file position.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_completion_tool,
    },
    "lsp_definition": {
        "name": "lsp_definition",
        "dangerous": False,
        "description": "Find definition location of a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_definition_tool,
    },
    "lsp_references": {
        "name": "lsp_references",
        "dangerous": False,
        "description": "Find all references to a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_references_tool,
    },
    "lsp_hover": {
        "name": "lsp_hover",
        "dangerous": False,
        "description": "Get type info and documentation for a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_hover_tool,
    },
    "sandbox_exec": {
        "name": "sandbox_exec",
        "dangerous": True,
        "description": "Execute code in a Docker sandbox (isolated environment). Language: python|javascript|bash.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {
                    "type": "string",
                    "description": "Language (python, javascript, bash)",
                    "default": "python",
                },
            },
            "required": ["code"],
        },
        "handler": sandbox_exec_tool,
    },
    "smart_edit": {
        "name": "smart_edit",
        "dangerous": True,
        "description": (
            "Edit a file using smart modes: old_text+new_text (replace), "
            "insert_after/new_text+insert_before, or append."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_text": {"type": "string", "description": "Text to replace (exact match)", "default": None},
                "new_text": {"type": "string", "description": "Replacement text", "default": None},
                "insert_after": {"type": "string", "description": "Insert new_text after this string", "default": None},
                "insert_before": {
                    "type": "string",
                    "description": "Insert new_text before this string",
                    "default": None,
                },
                "append": {"type": "boolean", "description": "Append new_text to file", "default": False},
            },
            "required": ["path"],
        },
        "handler": smart_edit_tool,
    },
    "patch": {
        "name": "patch",
        "dangerous": True,
        "description": "Apply a unified diff/patch to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to patch"},
                "diff_text": {"type": "string", "description": "Unified diff text"},
            },
            "required": ["path", "diff_text"],
        },
        "handler": patch_file_tool,
    },
    "format_file": {
        "name": "format_file",
        "dangerous": False,
        "description": "Auto-format a file using the appropriate formatter (ruff for .py, prettier for .ts/.js, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to format"},
            },
            "required": ["path"],
        },
        "handler": format_file_tool,
    },
    "format_files": {
        "name": "format_files",
        "dangerous": False,
        "description": "Auto-format multiple files.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "File paths to format"},
            },
            "required": ["paths"],
        },
        "handler": format_files_tool,
    },
    "auto_commit": {
        "name": "auto_commit",
        "dangerous": True,
        "description": "Automatically stage all changes and create a smart commit message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Optional custom commit message", "default": None},
                "path": {"type": "string", "description": "Git repo path", "default": None},
            },
            "required": [],
        },
        "handler": auto_commit_tool,
    },
    "skill": {
        "name": "skill",
        "dangerous": False,
        "description": (
            "Load a SKILL.md file for reusable instructions. Skills are discovered from "
            ".opencode/skills/, ~/.config/opencode/skills/, .claude/skills/, or .agents/skills/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the skill to load (without .md)"},
            },
            "required": ["name"],
        },
        "handler": load_skill,
    },
    "download_skill": {
        "name": "download_skill",
        "dangerous": False,
        "description": "Download a skill from the remote skill registry (ClawHub-like). Requires set_skill_registry first.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill ID to download"},
            },
            "required": ["name"],
        },
        "handler": download_skill,
    },
    "set_skill_registry": {
        "name": "set_skill_registry",
        "dangerous": False,
        "description": "Set the URL for the remote skill registry to download skills from.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Registry base URL (e.g. https://registry.example.com)"},
            },
            "required": ["url"],
        },
        "handler": set_skill_registry,
    },
    "todowrite": {
        "name": "todowrite",
        "dangerous": False,
        "description": "Create or update tasks in a structured todo list. Each task needs content and optional id/status.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of task dicts with content, optional id (defaults to incremental), "
                        "and optional status (pending/in_progress/completed/cancelled)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Task description"},
                            "id": {"type": "string", "description": "Optional task ID"},
                            "status": {
                                "type": "string",
                                "description": "Status: pending, in_progress, completed, cancelled",
                                "default": "pending",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            "required": ["tasks"],
        },
        "handler": todo_write,
    },
    "todolist": {
        "name": "todolist",
        "dangerous": False,
        "description": "Show the todo list, optionally filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: pending, in_progress, completed, cancelled",
                    "default": None,
                },
            },
            "required": [],
        },
        "handler": todo_list,
    },
    "todoupdate": {
        "name": "todoupdate",
        "dangerous": False,
        "description": "Update the status of a todo item.",
        "parameters": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "Task ID to update"},
                "status": {"type": "string", "description": "New status: pending, in_progress, completed, cancelled"},
            },
            "required": ["tid", "status"],
        },
        "handler": todo_update,
    },
    "todoclear": {
        "name": "todoclear",
        "dangerous": False,
        "description": "Clear all todo items.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": todo_clear,
    },
    "question": {
        "name": "question",
        "dangerous": False,
        "description": (
            "Ask the user a question with optional multiple-choice options. "
            "Use when you need clarification, preferences, or decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask the user"},
                "header": {"type": "string", "description": "Short header (max 30 chars)", "default": ""},
                "options": {
                    "type": "array",
                    "description": "Optional multiple-choice options",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Display text (1-5 words)"},
                            "description": {"type": "string", "description": "Explanation of choice"},
                        },
                        "required": ["label", "description"],
                    },
                    "default": [],
                },
                "multiple": {"type": "boolean", "description": "Allow selecting multiple choices", "default": False},
            },
            "required": ["question"],
        },
        "handler": question_tool,
    },
    "anchored_summary_read": {
        "name": "anchored_summary_read",
        "dangerous": False,
        "description": (
            "Read the current anchored summary. The summary persists across "
            "conversations and tracks progress, decisions, and context."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": anchored_summary_read,
    },
    "anchored_summary_write": {
        "name": "anchored_summary_write",
        "dangerous": False,
        "description": "Replace the entire anchored summary with new text. Use this to set or reset the persistent session note.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "New anchored summary text"},
            },
            "required": ["text"],
        },
        "handler": anchored_summary_write,
    },
    "anchored_summary_append": {
        "name": "anchored_summary_append",
        "dangerous": False,
        "description": "Append text to the existing anchored summary. Use this to log progress, decisions, or completed items.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to append"},
            },
            "required": ["text"],
        },
        "handler": anchored_summary_append,
    },
    "anchored_summary_clear": {
        "name": "anchored_summary_clear",
        "dangerous": False,
        "description": "Clear the anchored summary.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": anchored_summary_clear,
    },
    "browser_navigate": {
        "name": "browser_navigate",
        "dangerous": False,
        "description": "Navigate a browser to a URL using Playwright.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
        "handler": browser_navigate,
    },
    "browser_click": {
        "name": "browser_click",
        "dangerous": False,
        "description": "Click an element on the page using a CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector to click"},
            },
            "required": ["selector"],
        },
        "handler": browser_click,
    },
    "browser_type": {
        "name": "browser_type",
        "dangerous": False,
        "description": "Type text into an element on the page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the input element"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
        "handler": browser_type,
    },
    "browser_screenshot": {
        "name": "browser_screenshot",
        "dangerous": False,
        "description": "Take a screenshot of the current page.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to save screenshot", "default": "screenshot.png"},
            },
            "required": [],
        },
        "handler": browser_screenshot,
    },
    "browser_get_html": {
        "name": "browser_get_html",
        "dangerous": False,
        "description": "Get the inner HTML of an element (default: body).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector", "default": "body"},
            },
            "required": [],
        },
        "handler": browser_get_html,
    },
    "browser_evaluate": {
        "name": "browser_evaluate",
        "dangerous": True,
        "description": "Run JavaScript in the browser page and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "JavaScript code to evaluate"},
            },
            "required": ["script"],
        },
        "handler": browser_evaluate,
    },
    "browser_close": {
        "name": "browser_close",
        "dangerous": False,
        "description": "Close the browser and release resources.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": browser_close,
    },
    "canvas_render": {
        "name": "canvas_render",
        "dangerous": False,
        "description": "Render visual components (text, code, table, mermaid, link, image, list, alert) into formatted output",
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "List of component dicts with type, content, and optional fields",
                    "items": {"type": "object"},
                },
            },
            "required": ["components"],
        },
        "handler": _canvas_render_handler,
    },
    "nodes_list": {
        "name": "nodes_list",
        "dangerous": False,
        "description": "List all registered execution nodes for distributed task execution",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": _nodes_list_handler,
    },
    "cron_schedule": {
        "name": "cron_schedule",
        "dangerous": True,
        "description": "Schedule a recurring task using a cron expression",
        "parameters": {
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "Cron expression (e.g. '0 9 * * *')"},
                "task": {"type": "string", "description": "Task description"},
                "task_id": {"type": "string", "description": "Optional unique task ID"},
            },
            "required": ["cron", "task"],
        },
        "handler": _cron_schedule_handler,
    },
    "cron_list": {
        "name": "cron_list",
        "dangerous": False,
        "description": "List all active scheduled tasks",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": _cron_list_handler,
    },
    "cron_cancel": {
        "name": "cron_cancel",
        "dangerous": True,
        "description": "Cancel a scheduled task by its ID",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to cancel"},
            },
            "required": ["task_id"],
        },
        "handler": _cron_cancel_handler,
    },
    "sandbox_policy": {
        "name": "sandbox_policy",
        "dangerous": False,
        "description": (
            "Show or change the current sandbox security policy. Available: main, "
            "non-main, code-exec, web-browsing, read-only"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "policy": {"type": "string", "description": "Policy name to apply, or omit to show current"},
            },
            "required": [],
        },
        "handler": _sandbox_policy_handler,
    },
    "talk": {
        "name": "talk",
        "dangerous": False,
        "description": "Read text aloud using text-to-speech. Supports system, gtts, edge, elevenlabs providers.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to speak aloud"},
                "voice": {"type": "string", "description": "Voice ID (provider-specific)"},
                "provider": {"type": "string", "description": "TTS provider: system, gtts, edge, elevenlabs"},
            },
            "required": ["text"],
        },
        "handler": _talk_handler,
    },
}


_PLAN_MODE_DENIED = frozenset({"write", "edit", "bash", "task", "git_commit", "git_add", "checkpoint_restore", "redo"})

_plugin_tools_loaded = False


def _ensure_plugin_tools() -> None:
    global _plugin_tools_loaded
    if not _plugin_tools_loaded:
        try:
            from ravencode.runtime.plugins import get_plugin_registry

            reg = get_plugin_registry()
            for name, tool in reg.all_tools().items():
                if name not in MODULE_TOOLS:
                    MODULE_TOOLS[name] = tool
            _plugin_tools_loaded = True
        except ImportError:
            logger.debug("plugin tools unavailable, skipping")


def get_tool_definitions(plan_mode: bool = False) -> list[dict[str, Any]]:
    _ensure_plugin_tools()
    return list(_build_tool_definitions(plan_mode))


@functools.lru_cache(maxsize=2)
def _build_tool_definitions(plan_mode: bool) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in MODULE_TOOLS.values()
        if not plan_mode or t["name"] not in _PLAN_MODE_DENIED
    )


def is_dangerous(name: str) -> bool:
    t = MODULE_TOOLS.get(name)
    return t.get("dangerous", False) if t else False


@observe_tool(tool_name="execute_tool")
async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    _ensure_plugin_tools()
    tool = MODULE_TOOLS.get(name)
    if not tool:
        return f"[error] unknown tool: {name}"
    validation_error = validate_tool_arguments(name, tool.get("parameters", {}), arguments)
    if validation_error is not None:
        logger.warning("Tool call to '{}' rejected: {}", name, validation_error)
        return f"[validation_error] Invalid arguments for '{name}': {validation_error}. Fix your JSON and try again."
    perm = _get_permission_for_tool(name, arguments)
    if not perm[0]:
        return f"[denied] {perm[1]}"
    try:
        result = await tool["handler"](**arguments)
        if isinstance(result, list):
            result_str = "\n".join(str(r) for r in result[:200])
        else:
            result_str = str(result)
        if len(result_str) > 15_000:
            return result_str[:15_000] + "\n\n[... output truncated to 15k chars ...]"
        return result_str
    except QuestionError:
        raise
    except Exception as exc:
        logger.exception("Tool {} failed", name)
        return f"[execution_error] {name} failed: {exc}"


_PERMISSION_CHECKER: contextvars.ContextVar[Any] = contextvars.ContextVar("_PERMISSION_CHECKER", default=None)


def set_permission_checker(checker: Any) -> None:
    _PERMISSION_CHECKER.set(checker)


def _get_permission_for_tool(name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    checker = _PERMISSION_CHECKER.get()
    if checker is not None:
        result = checker(name, arguments)
        if isinstance(result, tuple) and len(result) == 2:
            return (bool(result[0]), str(result[1]))
    return True, ""
