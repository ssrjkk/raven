# Raven AI — Helm Chart

Deploy Raven AI on Kubernetes.

## Quick start

```bash
# Create namespace + secrets
kubectl create namespace raven
kubectl create secret generic auth-secret --namespace=raven --from-literal=jwt-secret=$(openssl rand -hex 32)
kubectl create secret generic grafana-admin --namespace=raven --from-literal=password=$(openssl rand -base64 16)

# Install
helm install raven ./deploy/helm/raven --namespace raven
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `global.namespace` | `raven` | Kubernetes namespace |
| `global.imageTag` | `latest` | Image tag for all services |
| `ingress.host` | `api.raven.local` | Ingress hostname |
| `secrets.jwtSecret` | `""` | JWT signing secret (required) |
| `secrets.grafanaPassword` | `""` | Grafana admin password (required) |
| `replicas.gateway` | `2` | Gateway replicas |
| `replicas.auth` | `2` | Auth service replicas |
| `autoscaling.gateway.enabled` | `true` | Enable HPA for gateway |
| `networkPolicy.enabled` | `true` | Enable network policies |

## Components

- **gateway** — API gateway (port 8000)
- **auth** — Authentication (port 8001 HTTP, 9001 gRPC)
- **agent-core** — LLM agent orchestration (port 8002)
- **monitor-engine** — Monitoring checks (port 8003)
- **rag-service** — RAG with Qdrant (port 8004)
- **task-engine** — Task execution (port 8005)
- **code-service** — Code indexing & search (port 8006)
- **nats** — Message bus (JetStream)
- **otel-collector** — OpenTelemetry collector
- **qdrant** — Vector database
- **tempo** — Distributed tracing
- **loki** — Log aggregation
- **prometheus** — Metrics
- **grafana** — Dashboards
- **traefik** — Ingress controller (optional)
