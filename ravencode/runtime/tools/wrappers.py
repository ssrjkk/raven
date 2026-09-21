from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from ravencode.runtime.undo import get_undo_manager
from ravencode.runtime.workspace import (
    _get_workspace,
)
from ravencode.runtime.workspace import (
    confine as _confine,
)

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




async def undo_changes_tool() -> str:
    """Revert workspace files to the most recent checkpoint (one-shot undo)."""
    from ravencode.runtime.checkpoints import get_checkpoint_manager

    mgr = get_checkpoint_manager()
    cps = await asyncio.to_thread(mgr.list)
    if not cps:
        return "[error] no checkpoint available — nothing to undo"
    return await mgr.restore(cps[-1]["id"])




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




async def lsp_diagnostics_tool(path: str) -> str:
    from ravencode.runtime.lsp import lsp_diagnostics

    return await lsp_diagnostics(path)




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
