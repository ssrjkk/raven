from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from raven.core.config import settings
from raven.core.logging import setup_logging

console = Console()

COMPOSE_CONTENT: dict[str, str] = {}


def _init_compose_templates() -> None:
    COMPOSE_CONTENT["minimal"] = """\
services:
  raven:
    build: .
    container_name: raven
    restart: unless-stopped
    ports:
      - "${RAVEN_WEB_PORT:-18888}:18888"
    environment:
      - RAVEN_LLM_PROVIDER=${RAVEN_LLM_PROVIDER:-openrouter}
      - RAVEN_DEFAULT_MODEL=${RAVEN_DEFAULT_MODEL:-openrouter/google/gemini-2.0-flash-001}
      - RAVEN_DM_POLICY=${RAVEN_DM_POLICY:-pairing}
    volumes:
      - ./data:/app/data
      - ./workspace:/app/workspace
      - ./plugins:/app/plugins
      - ./.env:/app/.env:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18888/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
"""

    COMPOSE_CONTENT["full"] = """\
services:
  raven:
    build: .
    container_name: raven
    restart: unless-stopped
    ports:
      - "${RAVEN_WEB_PORT:-18888}:18888"
    environment:
      - RAVEN_LLM_PROVIDER=${RAVEN_LLM_PROVIDER:-openrouter}
      - RAVEN_DEFAULT_MODEL=${RAVEN_DEFAULT_MODEL:-openrouter/google/gemini-2.0-flash-001}
      - RAVEN_DM_POLICY=${RAVEN_DM_POLICY:-pairing}
      - NATS_URL=nats://nats:4222
    volumes:
      - ./data:/app/data
      - ./workspace:/app/workspace
      - ./plugins:/app/plugins
      - ./.env:/app/.env:ro
    depends_on:
      nats:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18888/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nats:
    image: nats:latest
    container_name: raven-nats
    restart: unless-stopped
    ports:
      - "4222:4222"
      - "8222:8222"
    command: ["-js", "-m", "8222"]
    healthcheck:
      test: ["CMD", "nats", "ping", "-c", "1"]
      interval: 30s
      timeout: 5s
      retries: 3

  grafana:
    image: grafana/grafana:latest
    container_name: raven-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
    volumes:
      - grafana-data:/var/lib/grafana

  prometheus:
    image: prom/prometheus:latest
    container_name: raven-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - prometheus-data:/prometheus

volumes:
  grafana-data:
  prometheus-data:
"""

    COMPOSE_CONTENT["micro"] = """\
services:
  traefik:
    image: traefik:latest
    container_name: raven-traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./traefik/dynamic.yml:/etc/traefik/dynamic.yml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro

  nats:
    image: nats:latest
    container_name: raven-nats
    restart: unless-stopped
    ports:
      - "4222:4222"
    command: ["-js"]

  gateway:
    build: services/gateway
    container_name: raven-gateway
    restart: unless-stopped
    environment:
      - NATS_URL=nats://nats:4222
      - RAVEN_LLM_PROVIDER=${RAVEN_LLM_PROVIDER:-openrouter}
      - RAVEN_DEFAULT_MODEL=${RAVEN_DEFAULT_MODEL:-openrouter/google/gemini-2.0-flash-001}
    depends_on:
      - nats
      - auth

  auth:
    build: services/auth
    container_name: raven-auth
    restart: unless-stopped
    ports:
      - "50051"
    depends_on:
      - nats

  agent-core:
    build: services/agent-core
    container_name: raven-agent-core
    restart: unless-stopped
    depends_on:
      - nats
      - rag-service

  monitor-engine:
    build: services/monitor-engine
    container_name: raven-monitor-engine
    restart: unless-stopped
    depends_on:
      - nats

  rag-service:
    build: services/rag-service
    container_name: raven-rag-service
    restart: unless-stopped
    depends_on:
      - nats

  task-engine:
    build: services/task-engine
    container_name: raven-task-engine
    restart: unless-stopped
    depends_on:
      - nats

  code-service:
    build: services/code-service
    container_name: raven-code-service
    restart: unless-stopped
    depends_on:
      - nats
"""

    # Substitute port in healthcheck URLs
    for key in COMPOSE_CONTENT:
        COMPOSE_CONTENT[key] = COMPOSE_CONTENT[key].replace(
            "http://localhost:18888",
            f"http://localhost:{settings.web_port}",
        )


def _show_deploy_table(mode: str) -> None:
    details = {
        "minimal": "Raven only, no dependencies",
        "full": "Raven + NATS + Grafana + Prometheus",
        "micro": "15 microservices with Traefik routing",
    }
    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_row("Deployment mode", mode)
    table.add_row("Description", details.get(mode, ""))
    table.add_row("Output file", f"docker-compose.{mode}.yml")
    console.print(table)


def deploy() -> None:
    setup_logging()
    _init_compose_templates()

    console.print()
    console.print(Panel.fit("[bold cyan]raven deploy — Docker Compose Generator[/bold cyan]", border_style="cyan"))
    console.print()

    root = Path.cwd()
    existing = [f for f in root.glob("docker-compose*.yml") if f.is_file()]
    if existing and not Confirm.ask(
        f"Found {len(existing)} docker-compose file(s). Generate additional?", default=True
    ):
        console.print("[yellow]Aborted.[/yellow]")
        return

    mode = Prompt.ask("Deployment mode", choices=["minimal", "full", "micro"], default="minimal")
    _show_deploy_table(mode)

    if not Confirm.ask("Generate docker-compose file?", default=True):
        console.print("[yellow]Aborted.[/yellow]")
        return

    output = root / f"docker-compose.{mode}.yml"
    if output.exists() and not Confirm.ask(f"{output.name} exists. Overwrite?", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return

    content = COMPOSE_CONTENT[mode]
    output.write_text(content)
    console.print(f"[green]Written {output}[/green]")

    if mode == "micro":
        traefik_dir = root / "traefik"
        traefik_dir.mkdir(exist_ok=True)
        traefik_config = traefik_dir / "dynamic.yml"
        if not traefik_config.exists():
            traefik_config.write_text("""\
http:
  routers:
    api:
      rule: "PathPrefix(`/api`)"
      service: gateway
      middlewares:
        - cors
  services:
    gateway:
      loadBalancer:
        servers:
          - url: "http://gateway:8000"
  middlewares:
    cors:
      headers:
        accessControlAllowOriginList:
          - "http://localhost:5173"
          - "http://localhost:3000"
""")
            console.print(f"[green]Written {traefik_config}[/green]")

    console.print()
    name = output.name
    console.print(
        Panel.fit(
            "[bold green]Deployment scaffold created![/bold green]\n\n"
            "Next steps:\n"
            "  Copy [bold].env.example[/bold] to [bold].env[/bold]\n"
            f"  Run [bold]docker compose -f {name} up -d[/bold]\n"
            f"  Run [bold]docker compose -f {name} logs -f[/bold] to watch startup",
            border_style="green",
        )
    )
