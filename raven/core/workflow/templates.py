from __future__ import annotations

from raven.core.config import settings
from raven.core.workflow.models import TemplateCategory, TemplateTrigger, WorkflowTemplate
from raven.core.workflow.store import WorkflowStore

BUILTIN_TEMPLATES: list[WorkflowTemplate] = [
    WorkflowTemplate(
        id="morning-briefing",
        name="Morning Briefing",
        description="Daily morning summary: news highlights, weather, top tasks, and reminders",
        category=TemplateCategory.DAILY,
        trigger=TemplateTrigger.SCHEDULED,
        default_schedule="0 8 * * *",
        icon="🌅",
        config_schema={
            "type": "object",
            "properties": {
                "news_topics": {
                    "type": "string",
                    "description": "Comma-separated news topics of interest",
                    "default": "technology,ai",
                },
                "include_weather": {"type": "boolean", "description": "Include weather forecast", "default": True},
                "summary_length": {"type": "string", "enum": ["brief", "detailed"], "default": "brief"},
            },
        },
        steps_goal="Check recent news headlines, fetch weather if enabled, review today's scheduled tasks, "
        "and compose a concise morning briefing summary. Then send the briefing to the user's channel.",
    ),
    WorkflowTemplate(
        id="code-review",
        name="Code Review",
        description="Review pull request or code changes with automated analysis",
        category=TemplateCategory.DEV,
        default_schedule=None,
        icon="🔍",
        config_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to git repository"},
                "base_branch": {"type": "string", "description": "Base branch for comparison", "default": "main"},
                "review_depth": {"type": "string", "enum": ["quick", "thorough"], "default": "thorough"},
            },
            "required": ["repo_path"],
        },
        steps_goal="Examine the git diff between the current branch and base branch. "
        "Analyze changed files for code quality, security issues, and style. "
        "Generate a structured review report with findings, suggestions, and severity ratings.",
    ),
    WorkflowTemplate(
        id="price-monitor",
        name="Price Monitor",
        description="Track price of a product, stock, or cryptocurrency with alerts",
        category=TemplateCategory.MONITORING,
        trigger=TemplateTrigger.INTERVAL,
        default_interval=3600,
        icon="📈",
        config_schema={
            "type": "object",
            "properties": {
                "item_name": {"type": "string", "description": "Name of the item to track"},
                "url": {"type": "string", "description": "URL to scrape for price"},
                "target_price": {"type": "number", "description": "Alert when price drops below this"},
                "currency": {"type": "string", "default": "USD"},
            },
            "required": ["item_name", "url"],
        },
        steps_goal="Fetch the price from the provided URL. Compare with previous price and target. "
        "If price dropped below target, send an alert. Otherwise log the current price.",
    ),
    WorkflowTemplate(
        id="daily-report",
        name="Daily Report",
        description="Generate and send a daily activity report with metrics and summaries",
        category=TemplateCategory.DAILY,
        trigger=TemplateTrigger.SCHEDULED,
        default_schedule="0 18 * * *",
        icon="📋",
        config_schema={
            "type": "object",
            "properties": {
                "include_metrics": {"type": "boolean", "description": "Include system metrics", "default": True},
                "include_task_summary": {"type": "boolean", "description": "Include completed tasks", "default": True},
                "channels": {"type": "array", "items": {"type": "string"}, "description": "Channels to send report to"},
            },
        },
        steps_goal="Gather today's completed tasks, system metrics (CPU, memory, uptime), "
        "and recent activity logs. Compose a structured daily report and send it to the configured channels.",
    ),
    WorkflowTemplate(
        id="health-check",
        name="Health Check",
        description="Check service endpoints and system health, report status",
        category=TemplateCategory.MONITORING,
        trigger=TemplateTrigger.INTERVAL,
        default_interval=300,
        icon="❤️",
        config_schema={
            "type": "object",
            "properties": {
                "endpoints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to health-check",
                    "default": [f"http://localhost:{settings.web_port}/api/health/live"],
                },
                "timeout": {"type": "integer", "default": 10},
                "notify_on_failure": {"type": "boolean", "default": True},
            },
        },
        steps_goal="Ping each configured endpoint with HTTP GET. Check response status codes and response times. "
        "If any endpoint returns non-200 or times out, log failure and send alert. "
        "Summarize overall system health status.",
    ),
    WorkflowTemplate(
        id="data-backup",
        name="Data Backup",
        description="Backup SQLite database, workspace files, and vector store to local storage",
        category=TemplateCategory.DATA,
        trigger=TemplateTrigger.SCHEDULED,
        default_schedule="0 2 * * *",
        icon="💾",
        config_schema={
            "type": "object",
            "properties": {
                "backup_path": {"type": "string", "description": "Directory to store backups", "default": "backups/"},
                "include_workspace": {"type": "boolean", "default": True},
                "include_db": {"type": "boolean", "default": True},
                "max_backups": {"type": "integer", "default": 7, "description": "Keep only N most recent backups"},
            },
        },
        steps_goal="Create a timestamped backup directory. Copy SQLite database file (with WAL checkpoint). "
        "Copy workspace files. If configured, also backup vector store data. "
        "Remove backups older than max_backups. Log completion and size.",
    ),
    WorkflowTemplate(
        id="web-scraper",
        name="Web Scraper",
        description="Periodically fetch and extract content from a web page, track changes",
        category=TemplateCategory.DATA,
        trigger=TemplateTrigger.INTERVAL,
        default_interval=86400,
        icon="🕸️",
        config_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "selector": {"type": "string", "description": "CSS selector for content extraction"},
                "diff_previous": {"type": "boolean", "default": True, "description": "Show diff from last scrape"},
            },
            "required": ["url"],
        },
        steps_goal="Fetch the web page content. Extract text using the selector. "
        "Compare with previously scraped content if available. "
        "If diff_previous is enabled and content changed, highlight the differences. "
        "Store the latest content for future comparison.",
    ),
    WorkflowTemplate(
        id="social-digest",
        name="Social Media Digest",
        description="Collect and summarize recent posts from social feeds or RSS",
        category=TemplateCategory.COMMUNICATION,
        trigger=TemplateTrigger.SCHEDULED,
        default_schedule="0 9 * * *",
        icon="📱",
        config_schema={
            "type": "object",
            "properties": {
                "rss_feeds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "RSS feed URLs to monitor",
                },
                "max_items": {"type": "integer", "default": 10},
                "summary_style": {"type": "string", "enum": ["bullets", "paragraph"], "default": "bullets"},
            },
        },
        steps_goal="Fetch all configured RSS feeds. Collect recent items, deduplicate by URL. "
        "Summarize each item in the configured style. Compile into a digest and send to user.",
    ),
    WorkflowTemplate(
        id="weekly-retrospective",
        name="Weekly Retrospective",
        description="End-of-week summary: completed tasks, metrics, lessons, and next-week plan",
        category=TemplateCategory.DAILY,
        trigger=TemplateTrigger.SCHEDULED,
        default_schedule="0 17 * * 5",
        icon="📊",
        config_schema={
            "type": "object",
            "properties": {
                "include_changelog": {"type": "boolean", "default": True},
                "include_metrics": {"type": "boolean", "default": True},
                "format": {"type": "string", "enum": ["markdown", "html"], "default": "markdown"},
            },
        },
        steps_goal="Review tasks completed this week, examine git log for changes, "
        "collect system metrics averages. Compose a retrospective with achievements, "
        "challenges, and suggested focus areas for next week.",
    ),
    WorkflowTemplate(
        id="incident-response",
        name="Incident Response",
        description="Run diagnostics and collect data when a service incident is detected",
        category=TemplateCategory.DEV,
        icon="🚨",
        config_schema={
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Name of the affected service"},
                "error_log_path": {"type": "string", "description": "Path to error logs"},
                "auto_remediate": {"type": "boolean", "default": False},
            },
            "required": ["service_name"],
        },
        steps_goal="Check service status and recent logs. Collect error patterns and metrics. "
        "If auto_remediate is enabled, attempt restart. Compile incident report with "
        "timeline, impact, and recommended next steps.",
    ),
]


def register_builtin_templates(store: WorkflowStore) -> None:
    store.register_many(BUILTIN_TEMPLATES)
