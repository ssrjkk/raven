from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import click

from ravencode.cli.tui import tui_run
from ravencode.integrations.github import (
    GitHubIntegration,
    parse_github_webhook,
)
from ravencode.integrations.gitlab import GitLabIntegration, parse_gitlab_webhook


@click.group()
def cli():
    """RavenCode — Autonomous AI engineering framework."""


@cli.command()
@click.argument("project", required=False, default=".")
def tui(project: str) -> None:
    """Start the interactive TUI."""
    os.chdir(project)
    tui_run()


@cli.command()
@click.option("--host", default="127.0.0.1", help="Server host")
@click.option("--port", default=8080, help="Server port")
@click.option("--password", help="Basic auth password (env: RAVENCODE_SERVER_PASSWORD)")
@click.option("--username", default="ravencode", help="Basic auth username")
def serve(host: str, port: int, password: str | None, username: str) -> None:
    """Start headless HTTP server (OpenAI-compatible API)."""
    from ravencode.api.server import run_openai_server

    password = password or os.getenv("RAVENCODE_SERVER_PASSWORD", "")
    click.echo(f"Starting server on {host}:{port}")
    run_openai_server(host=host, port=port)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Web server host")
@click.option("--port", default=0, help="Web server port (0 = random)")
@click.option("--password", help="Basic auth password (env: RAVENCODE_SERVER_PASSWORD)")
def web(host: str, port: int, password: str | None) -> None:
    """Start server with web interface."""
    from ravencode.api.server import run_openai_server

    password = password or os.getenv("RAVENCODE_SERVER_PASSWORD", "")
    click.echo(f"Starting web server on {host}:{port or 'random'}")
    run_openai_server(host=host, port=port or 8081)


@cli.group()
def session():
    """Manage sessions."""


@session.command(name="list")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
def session_list(sessions_dir: str) -> None:
    """List all saved sessions."""
    p = Path(sessions_dir)
    if not p.is_dir():
        click.echo("No sessions directory found")
        return
    files = sorted(p.glob("*.json"))
    if not files:
        click.echo("No sessions found")
        return
    click.echo(f"Sessions ({len(files)}):")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("name", "") or data.get("config", {}).get("name", "")
            steps = data.get("steps", 0)
            click.echo(f"  {f.stem}  ({steps} steps)  {name}")
        except (json.JSONDecodeError, OSError):
            click.echo(f"  {f.stem}  (corrupt)")


@session.command(name="delete")
@click.argument("session_id")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
def session_delete(session_id: str, sessions_dir: str) -> None:
    """Delete a saved session."""
    p = Path(sessions_dir) / f"{session_id}.json"
    if p.exists():
        p.unlink()
        click.echo(f"Deleted session {session_id}")
    else:
        click.echo(f"Session {session_id} not found")
        sys.exit(1)


@session.command(name="export")
@click.argument("session_id")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
@click.option("--sanitize", is_flag=True, help="Strip API keys and secrets")
@click.option("--output", "-o", help="Output file path")
def session_export_cmd(session_id: str, sessions_dir: str, sanitize: bool, output: str | None) -> None:
    """Export a session as JSON."""
    session_export_func(session_id, sessions_dir, sanitize, output)


@session.command(name="import")
@click.argument("source")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
def session_import_cmd(source: str, sessions_dir: str) -> None:
    """Import a session from JSON file or URL."""
    session_import_func(source, sessions_dir)


def session_export_func(session_id: str, sessions_dir: str, sanitize: bool, output: str | None) -> None:
    p = Path(sessions_dir) / f"{session_id}.json"
    if not p.exists():
        click.echo(f"Session {session_id} not found")
        sys.exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    if sanitize:
        _sanitize_session(data)
    out = output or f"{session_id}.json"
    Path(out).write_text(json.dumps(data, indent=2), encoding="utf-8")
    click.echo(f"Exported to {out}")


def session_import_func(source: str, sessions_dir: str) -> None:
    if source.startswith("http://") or source.startswith("https://"):
        import httpx
        try:
            resp = httpx.get(source, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            click.echo(f"Failed to fetch URL: {e}")
            sys.exit(1)
    else:
        p = Path(source)
        if not p.exists():
            click.echo(f"File {source} not found")
            sys.exit(1)
        data = json.loads(p.read_text(encoding="utf-8"))

    sid = data.get("id", data.get("session_id", "imported"))
    out_dir = Path(sessions_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sid}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    click.echo(f"Imported session {sid}")


def _sanitize_session(data: dict[str, Any]) -> None:
    sensitive_keys = {"api_key", "token", "secret", "password", "key"}
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if k.lower() in sensitive_keys and isinstance(v, str):
                data[k] = "***"
            elif isinstance(v, dict):
                _sanitize_session(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        _sanitize_session(item)


@cli.group()
def auth():
    """Manage credentials and API keys."""


@auth.command(name="login")
@click.option("--provider", "-p", default="openrouter", help="Provider name")
@click.option("--key", "-k", help="API key (omit for prompt)")
@click.option("--base-url", help="Custom base URL")
def auth_login(provider: str, key: str | None, base_url: str | None) -> None:
    """Configure API key for a provider."""

    creds_dir = Path.home() / ".config" / "ravencode"
    creds_dir.mkdir(parents=True, exist_ok=True)
    creds_file = creds_dir / "auth.json"

    creds: dict[str, Any] = {}
    if creds_file.exists():
        creds = json.loads(creds_file.read_text(encoding="utf-8"))

    if provider not in creds:
        creds[provider] = {}

    if key is None:
        key = click.prompt(f"Enter API key for {provider}", hide_input=True)
    creds[provider]["api_key"] = key
    if base_url:
        creds[provider]["base_url"] = base_url

    creds_file.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    click.echo(f"Saved credentials for {provider}")


@auth.command(name="list")
def auth_list() -> None:
    """List configured providers."""
    creds_file = Path.home() / ".config" / "ravencode" / "auth.json"
    if not creds_file.exists():
        click.echo("No credentials configured")
        click.echo("Run: ravencode auth login --provider <name>")
        return
    creds = json.loads(creds_file.read_text(encoding="utf-8"))
    for provider, config in creds.items():
        has_key = bool(config.get("api_key"))
        url = config.get("base_url", "")
        click.echo(f"  {provider}: {'✓ configured' if has_key else '✗ no key'} {url}")


@auth.command(name="logout")
@click.argument("provider", required=False)
def auth_logout(provider: str | None) -> None:
    """Remove credentials for a provider or all."""
    creds_file = Path.home() / ".config" / "ravencode" / "auth.json"
    if not creds_file.exists():
        click.echo("No credentials to remove")
        return
    creds = json.loads(creds_file.read_text(encoding="utf-8"))
    if provider:
        creds.pop(provider, None)
        click.echo(f"Removed credentials for {provider}")
    else:
        creds = {}
        click.echo("Removed all credentials")
    creds_file.write_text(json.dumps(creds, indent=2), encoding="utf-8")


@cli.command(name="models")
@click.option("--refresh", is_flag=True, help="Refresh model cache")
@click.option("--verbose", is_flag=True, help="Show full model details")
def models_cmd(refresh: bool, verbose: bool) -> None:
    """List available models from all configured providers."""
    from ravencode.config.loader import get_config

    cfg = get_config()
    providers = cfg.resolve_providers()
    if not providers:
        click.echo("No providers configured in ravencode.json")
        return

    for prov in providers:
        click.echo(f"\n{prov.name or prov.id}:")
        if prov.models:
            for m in prov.models:
                extra = f" ({prov.base_url})" if verbose and prov.base_url else ""
                click.echo(f"  - {m}{extra}")
        else:
            click.echo("  (no models listed)")


@cli.command()
@click.option("--version", help="Target version (default: latest)")
def upgrade(version: str | None) -> None:
    """Upgrade ravencode to the latest version."""
    import subprocess
    import sys

    click.echo("Checking for updates...")
    try:
        pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
        if version:
            pip_cmd.append(f"ravencode=={version}")
        else:
            pip_cmd.append("ravencode")
        result = subprocess.run(pip_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            click.echo("Upgrade successful!")
        else:
            click.echo(f"Upgrade failed: {result.stderr}")
            sys.exit(1)
    except FileNotFoundError:
        click.echo("Error: pip not found")
        sys.exit(1)


@cli.command(name="export")
@click.option("--session", "session_id", help="Session ID to export")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
@click.option("--sanitize", is_flag=True, help="Strip sensitive data")
@click.option("--output", "-o", help="Output file")
def export_cmd(session_id: str | None, sessions_dir: str, sanitize: bool, output: str | None) -> None:
    """Export session data as JSON."""
    if session_id:
        session_export_func(session_id, sessions_dir, sanitize, output)
    else:
        click.echo("Use: ravencode session export <id>")


@cli.command(name="import")
@click.argument("source")
@click.option("--dir", "sessions_dir", default="data/sessions", help="Sessions directory")
def import_cmd(source: str, sessions_dir: str) -> None:
    """Import a session from JSON file or share URL."""
    session_import_func(source, sessions_dir)


@cli.group()
def integrations():
    """Manage CI/CD integrations."""


@integrations.group()
def github():
    """GitHub integration commands."""


@github.command(name="install")
@click.option("--repo", help="Repository to install (owner/repo)")
@click.option("--token", help="GitHub token (default: GITHUB_TOKEN env)")
def github_install(repo: str | None, token: str | None) -> None:
    """Install ravencode GitHub Actions workflow."""
    token = token or os.getenv("GITHUB_TOKEN", "")
    if not token:
        click.echo("Error: GITHUB_TOKEN required. Set --token or GITHUB_TOKEN env var.")
        sys.exit(1)

    if repo:
        parts = repo.split("/", 1)
        if len(parts) != 2:
            click.echo("Error: repo must be in owner/repo format")
            sys.exit(1)

    click.echo("RavenCode GitHub integration configured.")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Commit and push .github/workflows/ravencode.yml")
    click.echo("  2. Add secrets to your repo:")
    click.echo("     - ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY")
    click.echo("  3. Comment `/ravencode explain` on any issue to test")
    click.echo()
    click.echo("For webhook mode (real-time, no polling):")
    click.echo("  ravencode integrations github webhook --port 8080")


@github.command(name="webhook")
@click.option("--port", default=8080, help="Webhook server port")
@click.option("--host", default="0.0.0.0", help="Webhook server host")
@click.option("--token", help="GitHub token (default: GITHUB_TOKEN env)")
@click.option("--secret", help="GitHub webhook secret for verification")
def github_webhook(port: int, host: str, token: str | None, secret: str | None) -> None:
    """Start a webhook server for GitHub events."""
    from ravencode.integrations.github_webhook import run_webhook_server

    run_webhook_server(host=host, port=port, token=token, secret=secret)


@github.command(name="run")
@click.option("--event-name", default="", help="GitHub event name")
@click.option("--payload", default="", help="Base64-encoded GitHub event payload")
@click.option("--token", help="GitHub token (default: GITHUB_TOKEN env)")
def github_run(event_name: str, payload: str, token: str | None) -> None:
    """Run ravencode in GitHub Actions CI context."""
    import base64

    token = token or os.getenv("GITHUB_TOKEN", "")

    payload_str = payload
    if not payload_str:
        payload_b64 = os.getenv("RAVENCODE_GITHUB_EVENT")
        if payload_b64:
            payload_str = base64.b64decode(payload_b64).decode("utf-8")
        else:
            payload_str = os.getenv("RAVENCODE_GITHUB_EVENT", "{}")

    event_name = event_name or os.getenv("RAVENCODE_GITHUB_EVENT_NAME", "")
    try:
        payload_data = json.loads(payload_str)
    except json.JSONDecodeError:
        click.echo("Error: invalid JSON payload")
        sys.exit(1)

    ctx = parse_github_webhook(event_name, payload_data)
    if ctx is None:
        click.echo("No matching event type")
        return

    integration = GitHubIntegration(token=token)
    result = asyncio.run(integration.handle_event(ctx))
    if result:
        click.echo(f"Result: {result.summary}")
    else:
        click.echo("No action taken")


@integrations.group()
def gitlab():
    """GitLab integration commands."""


@gitlab.command(name="install")
@click.option("--project", help="GitLab project path")
@click.option("--token", help="GitLab token (default: GITLAB_TOKEN env)")
def gitlab_install(project: str | None, token: str | None) -> None:
    """Install ravencode GitLab CI template."""
    token = token or os.getenv("GITLAB_TOKEN", "")
    if not token:
        click.echo("Error: GITLAB_TOKEN required.")
        sys.exit(1)

    click.echo("RavenCode GitLab integration configured.")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Add to your .gitlab-ci.yml:")
    click.echo("       include:")
    click.echo("         - local: ravencode/integrations/gitlab_ci.yml")
    click.echo("  2. Set CI/CD variables:")
    click.echo("     - ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY")
    click.echo("     - GITLAB_TOKEN (with api scope)")
    click.echo("  3. Comment `/ravencode explain` on any issue to test")


@gitlab.command(name="run")
@click.option("--token", help="GitLab token (default: GITLAB_TOKEN env)")
@click.option("--api-url", help="GitLab API URL")
def gitlab_run(token: str | None, api_url: str | None) -> None:
    """Run ravencode in GitLab CI context."""
    token = token or os.getenv("GITLAB_TOKEN", "")
    event_name = os.getenv("CI_MERGE_REQUEST_EVENT_TYPE", "Issue Hook")
    payload_str = os.getenv("RAVENCODE_GITLAB_EVENT", "{}")

    try:
        payload_data = json.loads(payload_str)
    except json.JSONDecodeError:
        click.echo("Error: invalid event payload")
        sys.exit(1)

    ctx = parse_gitlab_webhook(event_name, payload_data)
    if ctx is None:
        click.echo("No matching event type")
        return

    integration = GitLabIntegration(token=token, api_url=api_url or "")
    result = asyncio.run(integration.handle_event(ctx))
    if result:
        click.echo(f"Result: {result.summary}")
    else:
        click.echo("No action taken")
