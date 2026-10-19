from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import uvloop

    uvloop.install()
except ImportError:
    logger.debug("uvloop not available, using asyncio")

import click

from raven.core._json import json
from raven.core.config import data_path
from raven.core.logging import setup_logging
from raven.core.stdio import use_utf8_console
from raven.core.version import __version__
from ravencode.cli.tui import tui_run
from ravencode.integrations.github import (
    GitHubIntegration,
    parse_github_webhook,
)
from ravencode.integrations.gitlab import GitLabIntegration, parse_gitlab_webhook
from ravencode.runtime.session import validate_session_id

use_utf8_console()


@click.group()
@click.version_option(
    version=__version__,
    prog_name="ravencode",
    message="%(prog)s %(version)s — by ssrjkk",
)
def cli() -> None:
    """RavenCode — Autonomous AI engineering framework."""
    setup_logging()


@cli.command()
@click.argument("project", required=False, default=".")
def tui(project: str) -> None:
    """Start the interactive TUI."""
    try:
        os.chdir(project)
    except OSError:
        click.echo(f"No such directory: {project}")
        sys.exit(1)
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
    run_openai_server(host=host, port=port, username=username, password=password)


@cli.group()
def session() -> None:
    """Manage sessions."""


def _safe_session_id(session_id: str) -> str:
    """Session ids become filenames; reject anything that could escape the sessions dir."""
    try:
        return validate_session_id(session_id)
    except ValueError:
        click.echo(f"Invalid session id: {session_id!r}")
        sys.exit(1)


def _sessions_dir(sessions_dir: str) -> Path:
    return Path(sessions_dir) if sessions_dir else data_path("sessions")


@session.command(name="list")
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
def session_list(sessions_dir: str) -> None:
    """List all saved sessions."""
    p = _sessions_dir(sessions_dir)
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


@session.command(name="resume")
@click.argument("session_id")
def session_resume(session_id: str) -> None:
    """Resume a saved session in the TUI."""
    tui_run(session_id=session_id)


@session.command(name="delete")
@click.argument("session_id")
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
def session_delete(session_id: str, sessions_dir: str) -> None:
    """Delete a saved session."""
    p = _sessions_dir(sessions_dir) / f"{_safe_session_id(session_id)}.json"
    if p.exists():
        p.unlink()
        click.echo(f"Deleted session {session_id}")
    else:
        click.echo(f"Session {session_id} not found")
        sys.exit(1)


@session.command(name="export")
@click.argument("session_id")
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
@click.option("--sanitize", is_flag=True, help="Strip API keys and secrets")
@click.option("--output", "-o", help="Output file path")
def session_export_cmd(session_id: str, sessions_dir: str, sanitize: bool, output: str | None) -> None:
    """Export a session as JSON."""
    session_export_func(session_id, sessions_dir, sanitize, output)


@session.command(name="import")
@click.argument("source")
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
def session_import_cmd(source: str, sessions_dir: str) -> None:
    """Import a session from JSON file or URL."""
    session_import_func(source, sessions_dir)


def session_export_func(session_id: str, sessions_dir: str, sanitize: bool, output: str | None) -> None:
    session_id = _safe_session_id(session_id)
    p = _sessions_dir(sessions_dir) / f"{session_id}.json"
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
    if source.startswith(("http://", "https://")):
        from raven.core.security.ssrf import safe_fetch_async

        try:
            resp = asyncio.run(safe_fetch_async(source))
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

    sid = _safe_session_id(str(data.get("id") or data.get("session_id") or "imported"))
    out_dir = _sessions_dir(sessions_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sid}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    click.echo(f"Imported session {sid}")


_MASK = "***"

# Key names that always carry a credential; the separators keep "monkey"/"tokenizer"/"keyboard" out.
_SECRET_KEY_RE = re.compile(
    r"(?:^|[^a-zA-Z])(?:api[_-]?keys?|access[_-]?keys?|secrets?|tokens?|passwords?|passwd|"
    r"credentials?|authorization|private[_-]?keys?|keys?)(?:$|[^a-zA-Z])",
    re.IGNORECASE,
)

# Secret shapes that leak through message text, header lists and env dicts where no key name hints at them.
_SECRET_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9-]{6,}|sk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{16,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[A-Za-z0-9-]{6,}|"
    r"AKIA[0-9A-Z]{16}|npm_[A-Za-z0-9]{20,})"
    r"|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


def _sanitize_session(data: Any) -> None:
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                data[k] = _MASK
            elif isinstance(v, str):
                masked = _SECRET_VALUE_RE.sub(_MASK, v)
                if masked != v:
                    data[k] = masked
            else:
                _sanitize_session(v)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, str):
                masked = _SECRET_VALUE_RE.sub(_MASK, item)
                if masked != item:
                    data[i] = masked
            else:
                _sanitize_session(item)


@cli.group()
def auth() -> None:
    """Manage credentials and API keys."""


def _save_creds(creds_file: Path, creds: dict[str, Any]) -> None:
    creds_file.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    # Same convention as raven.core.config: provider keys are never world-readable.
    with contextlib.suppress(OSError):
        creds_file.chmod(0o600)


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

    _save_creds(creds_file, creds)
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
    _save_creds(creds_file, creds)


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
        pip_cmd = [sys.executable, "-X", "utf8", "-m", "pip", "install", "--upgrade"]
        if version:
            pip_cmd.append(f"raven-agent=={version}")
        else:
            pip_cmd.append("raven-agent")
        result = subprocess.run(
            pip_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
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
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
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
@click.option("--dir", "sessions_dir", default="", help="Sessions directory (default: sessions under the data dir)")
def import_cmd(source: str, sessions_dir: str) -> None:
    """Import a session from JSON file or share URL."""
    session_import_func(source, sessions_dir)


@cli.group()
def integrations() -> None:
    """Manage CI/CD integrations."""


@integrations.group()
def github() -> None:
    """GitHub integration commands."""


@github.command(name="install")
@click.option("--force", is_flag=True, help="Overwrite an existing workflow file")
def github_install(force: bool) -> None:
    """Install the RavenCode GitHub Actions workflow into this repository."""
    template = Path(__file__).resolve().parent.parent / "integrations" / "github_workflow.yml"
    target = Path.cwd() / ".github" / "workflows" / "ravencode.yml"
    if target.exists() and not force:
        click.echo(f"{target} already exists. Use --force to overwrite.")
        sys.exit(1)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    click.echo(f"Wrote {target}")
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
@click.option("--host", default="127.0.0.1", help="Webhook server host")
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
    import binascii

    token = token or os.getenv("GITHUB_TOKEN", "")

    raw = payload or os.getenv("RAVENCODE_GITHUB_EVENT", "")
    if raw:
        try:
            payload_str = base64.b64decode(raw, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            click.echo("Error: payload must be base64-encoded JSON")
            sys.exit(1)
    else:
        payload_str = "{}"

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
def gitlab() -> None:
    """GitLab integration commands."""


@gitlab.command(name="install")
@click.option("--force", is_flag=True, help="Overwrite an existing CI file")
def gitlab_install(force: bool) -> None:
    """Install the RavenCode GitLab CI template into this repository."""
    template = Path(__file__).resolve().parent.parent / "integrations" / "gitlab_ci.yml"
    target = Path.cwd() / ".gitlab-ci-ravencode.yml"
    if target.exists() and not force:
        click.echo(f"{target} already exists. Use --force to overwrite.")
        sys.exit(1)

    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    click.echo(f"Wrote {target}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Add to your .gitlab-ci.yml:")
    click.echo("       include:")
    click.echo('         - local: ".gitlab-ci-ravencode.yml"')
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
