from __future__ import annotations

import asyncio

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_cleanup_tasks: set[asyncio.Task[None]] = set()


def workflow_list_templates(category: str = "") -> str:
    from raven.core.workflow.templates import BUILTIN_TEMPLATES

    templates = BUILTIN_TEMPLATES if not category else [t for t in BUILTIN_TEMPLATES if t.category.value == category]
    if not templates:
        return "No templates found."
    lines: list[str] = []
    for t in templates:
        lines.append(f"- **{t.name}** (`{t.id}`): {t.description}")
    return "\n".join(lines)


def workflow_list_categories() -> str:
    from raven.core.workflow.models import TemplateCategory

    cats = [c.value for c in TemplateCategory]
    return f"Categories: {', '.join(cats)}"


def workflow_get_template(template_id: str) -> str:
    from raven.core.workflow.templates import BUILTIN_TEMPLATES

    for t in BUILTIN_TEMPLATES:
        if t.id == template_id:
            lines = [f"**{t.name}** (`{t.id}`)"]
            lines.append(f"Description: {t.description}")
            lines.append(f"Category: {t.category.value}")
            lines.append(f"Trigger: {t.trigger.value}")
            if t.config_schema.get("properties"):
                lines.append("Config parameters:")
                for key, prop in t.config_schema["properties"].items():
                    req = key in t.config_schema.get("required", [])
                    lines.append(f"  - `{key}` ({'required' if req else 'optional'}): {prop.get('description', '')}")
            lines.append(f"\nGoal: {t.steps_goal}")
            return "\n".join(lines)
    return f"Template '{template_id}' not found."


async def workflow_instantiate(template_id: str, config_json: str = "{}") -> str:
    import json

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        return f"Invalid config JSON: {e}"
    from raven.core.config import settings
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.store import TaskStore
    from raven.core.workflow.runner import TemplateRunner
    from raven.core.workflow.templates import BUILTIN_TEMPLATES
    from raven.tools.register_all import create_tool_registry

    template = None
    for t in BUILTIN_TEMPLATES:
        if t.id == template_id:
            template = t
            break
    if not template:
        return f"Template '{template_id}' not found."
    tools = create_tool_registry()
    store = TaskStore(settings.resolved_db_path)
    runner = TaskRunner(store, tools)
    tpl_runner = TemplateRunner(runner, store, tools, None)
    try:
        task_id = await tpl_runner.instantiate(template=template, user_id="system", channel="internal", config=config)

        def _close_store() -> None:
            task = asyncio.create_task(store.close())

            def _cleanup_done(_t: asyncio.Task[None]) -> None:
                _cleanup_tasks.discard(_t)

            task.add_done_callback(_cleanup_done)
            _cleanup_tasks.add(task)

        runner.on_complete(task_id, _close_store)
        return f"Instantiated '{template.name}' as task `{task_id}`."
    except Exception as e:
        await store.close()
        return f"Failed to instantiate: {e}"


async def workflow_schedule(template_id: str, config_json: str = "{}") -> str:
    import json

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        return f"Invalid config JSON: {e}"
    from raven.core.config import settings
    from raven.core.workflow.runner import TemplateRunner
    from raven.core.workflow.templates import BUILTIN_TEMPLATES

    template = None
    for t in BUILTIN_TEMPLATES:
        if t.id == template_id:
            template = t
            break
    if not template:
        return f"Template '{template_id}' not found."
    try:
        routine_id = await TemplateRunner.schedule_as_routine(
            template=template,
            db_path=str(settings.resolved_db_path),
            user_id="system",
            channel="internal",
            config=config,
        )
        return f"Scheduled '{template.name}' as routine `{routine_id}`."
    except Exception as e:
        return f"Failed to schedule: {e}"


def register_workflow_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="workflow_list_templates",
            description="List all available workflow templates, optionally filtered by category",
            parameters={
                "category": {
                    "type": "string",
                    "description": "Filter by category (daily, dev, monitoring, data, communication)",
                    "required": False,
                },
            },
            handler=workflow_list_templates,
            category="automation",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="workflow_list_categories",
            description="List all workflow template categories",
            parameters={},
            handler=workflow_list_categories,
            category="automation",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="workflow_get_template",
            description="Get details of a specific workflow template by ID",
            parameters={
                "template_id": {
                    "type": "string",
                    "description": "Template ID (e.g. morning-briefing, code-review)",
                    "required": True,
                },
            },
            handler=workflow_get_template,
            category="automation",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="workflow_instantiate",
            description="Instantiate a workflow template as a runnable task",
            parameters={
                "template_id": {"type": "string", "description": "Template ID to instantiate", "required": True},
                "config_json": {
                    "type": "string",
                    "description": "JSON config with template parameters",
                    "required": False,
                },
            },
            handler=workflow_instantiate,
            category="automation",
            timeout=120,
        )
    )
    registry.register(
        ToolSpec(
            name="workflow_schedule",
            description="Schedule a workflow template as a recurring routine",
            parameters={
                "template_id": {"type": "string", "description": "Template ID to schedule", "required": True},
                "config_json": {
                    "type": "string",
                    "description": "JSON config with template parameters",
                    "required": False,
                },
            },
            handler=workflow_schedule,
            category="automation",
            timeout=120,
        )
    )
