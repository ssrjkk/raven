# RAVEN MONOLITH → MICROSERVICES MIGRATION
# Версия: 1.0 | Статус: ВСЕ ФАЗЫ ЗАВЕРШЕНЫ

---

## [ФАЗА 1] Domain Decomposition & Bounded Contexts

**Решение**: Выделено 7 микросервисов на основе бизнес-границ монолита. Каждый сервис владеет своей БД и данными. Shared libraries только: `proto/`, `shared-types/`, `observability-sdk/`.

**Артефакты**:
- `services/proto/{auth,agent,channel,monitor,rag,task,session}/v1/*.proto` — 7 protobuf контрактов
- `services/{gateway,auth,agent-core,monitor-engine,rag-service,task-engine,code-service}/` — entrypoints (main.py, routes.py, Dockerfile)
- `services/observability_sdk/` — OpenTelemetry + JSON logging
- `docker-compose.micro.yml` — 14 сервисов (Traefik, NATS, 7 микросервисов, Qdrant, OTel, Tempo, Loki, Prometheus, Grafana)
- `services/proto/buf.yaml` + `buf.gen.yaml` — Buf lint/breaking/gen конфиг

**Код/Конфиг**:
```bash
docker compose -f docker-compose.micro.yml up -d
```

**Границы сервисов**:

| Сервис | Входит | Исключено |
|--------|--------|-----------|
| **gateway** | Router, auth middleware, rate-limit, request validation | Бизнес-логика, работа с БД |
| **auth** | JWT, RBAC, регистрация/логин, token validation | LLM, мониторы, задачи |
| **agent-core** | LLM routing, session state, conversation logic | Хранение документов, исполнение кода |
| **monitor-engine** | Check scheduling, health probes, alert dispatch | UI, user management |
| **rag-service** | Vector search, document indexing, embeddings | LLM вызовы, авторизация |
| **task-engine** | Task execution, tool sandbox, policy enforcement | RAG, мониторинг |
| **code-service** | Code sandbox, compilation, test execution | Task orchestration |

**Коммуникация**:
- External clients → REST (`/api/v1/`) через Traefik gateway
- Service-to-service sync → gRPC (`v1` packages)
- Async events → NATS JetStream (5 streams, typed schemas)

**Данные**: SQLite embedded per service (временное решение). PostgreSQL per-service — Фаза 3.

**Наблюдаемость**: `/health`, `/ready`, `/metrics` на каждом сервисе. OpenTelemetry → OTel Collector → Tempo (traces) + Loki (logs) + Prometheus (metrics).

**Тесты**: Unit (pytest), Contract (buf lint, proto contract tests), Proto compatibility (buf breaking).

**Оценка**: ~40 часов, риск Medium. Точки отказа: shared-types import paths, protobuf wire compatibility.

**Критерий приёмки**: `docker compose up` стартует 14 контейнеров, `curl localhost:8000/health` → 200.

---

## [ФАЗА 2] Communication & Data Architecture

**Решение**: API Gateway (Traefik v3) + Message Broker (NATS JetStream) + gRPC service-to-service + REST для external clients. Event Schema Registry на Python dataclasses + protobuf.

**Артефакты**:
- `deploy/traefik/dynamic.yml` — 7 routers, 8 services, middleware chain (rate-limit, CORS, CB, retry, compression)
- `deploy/nats/nats.conf` — 5 JetStream streams, 3 consumers, file-backed persistence, 30s dedup
- `services/shared-types/raven/shared/events.py` — EventEnvelope, EVENT_SCHEMA_REGISTRY, 10+ typed event classes
- `services/shared-types/raven/shared/nats.py` — NATS subject templates (source.event.version), consumer group map
- `services/observability_sdk/outbox.py` — Transactional Outbox (SQLite, idempotent enqueue, at-least-once)
- `services/observability_sdk/outbox_poller.py` — Background poller → NATS publisher
- `services/observability_sdk/circuit_breaker.py` — Circuit Breaker (closed → open → half-open, configurable thresholds)
- `services/observability_sdk/retry.py` — Retry policy (exponential backoff + jitter, 4 presets)
- `services/observability_sdk/idempotency.py` — IdempotencyKey store (SQLite, 24h TTL) + FastAPI middleware
- `services/observability_sdk/saga.py` — SAGA choreography coordinator + UserRegistrationSaga example
- `deploy/nats/nats-stream-manager.py` — CLI: list/create/delete streams, consumers, verify, validate

**Код/Конфиг**:
```python
# Outbox usage
store = OutboxStore(db_path="/data/outbox.db", service_name="auth")
store.enqueue("auth.user.created", {"user_id": "u123"}, idempotency_key="req-abc")

# Circuit Breaker usage
cb = CircuitBreaker("rag-search", failure_threshold=5, recovery_timeout=30.0)
result = await cb.call(rag_service.search, query="test")

# Idempotency middleware (FastAPI)
app.middleware("http")(idempotency_middleware)

# SAGA
results = await UserRegistrationSaga.run(user_id="u123", username="alice", email="a@b.com")
```

**Границы**: Outbox гарантирует at-least-once delivery. Idempotency keys — exactly-once processing. SAGA — eventual consistency.

**Коммуникация**:
```
Service → OutboxStore → OutboxPoller → NATS JetStream → Consumer → Service
                                                                        ↓
                                                                   IdempotencyKey check
                                                                        ↓
                                                                   Process event
```

**Данные**: Каждый сервис имеет SQLite БД с outbox + idempotency таблицами.

**Наблюдаемость**: Circuit Breaker metrics (transitions, rejected, successes, failures). Outbox backlog count. SAGA compensation counter. Все через Prometheus `/metrics`.

**Тесты**: Outbox (7), Circuit Breaker (8), Retry (6), SAGA (4), Idempotency (5), Proto contracts (49).

**Оценка**: ~60 часов, риск Medium-High. Точки отказа: NATS гонки при старте, outbox deadlock при сбое poller'a.

**Критерий приёмки**: 641 тест проходит (115 service tests). `python deploy/nats/nats-stream-manager.py verify` показывает все 5 streams.

---

## [ФАЗА 3] Infrastructure & Deployment Blueprint

**Решение**: docker-compose с resource limits + CI/CD canary deploy + env management per service.

**Артефакты**:
- `deploy/env/{gateway,auth,agent-core,monitor-engine,rag-service,task-engine,code-service,observability}.env` — 8 env файлов
- `docker-compose.micro.yml` — resource limits (`cpus: "0.5"`, `memory: "256M"`) per service, healthchecks, depends_on, named volumes
- `.github/workflows/ci.yml` — lint → pytest → docker build matrix (7 images)
- `.github/workflows/canary.yml` — lint → build → canary deploy (10% traffic) → health check → promote → rollback
- `.github/workflows/protolint.yml` — buf lint + buf breaking на каждый PR
- `deploy/task-policy.yaml` — allowed/denied tools, timeouts, blocked hosts
- `monolith-requirements.txt` — locked Python deps (FastAPI, NATS, gRPC, OTel, Prometheus)
- `setup.cfg` — pytest/pact config

**Код/Конфиг**:
```yaml
# docker-compose resource limits per service
x-resources: &svc-resources
  deploy:
    resources:
      limits:
        cpus: "0.5"
        memory: "256M"
      reservations:
        cpus: "0.1"
        memory: "64M"

# RAG and Agent get more resources
rag-service:
  deploy:
    resources:
      limits:
        cpus: "1.0"
        memory: "1G"
```

```bash
# CI/CD pipeline order
ruff check . → pytest tests/ → docker buildx build → docker push ghcr.io
→ canary deploy (10% traffic) → health check → promote stable → rollback on failure
```

**Границы**: CI/CD собирает все 7 сервисов. `canary.yml` срабатывает только на `main` при изменениях в `services/` или `deploy/`.

**Коммуникация**: GitHub Actions → GHCR → docker compose pull → docker compose up -d

**Данные**: Названные volumes (`gateway_data`, `auth_data`, etc.) — persist между рестартами.

**Наблюдаемость**: GitHub Actions logs + health check steps в пайплайне.

**Оценка**: ~16 часов, риск Low. Точки отказа: GHCR rate limits, docker build cache miss.

**Критерий приёмки**: `docker compose -f docker-compose.micro.yml config` валиден. GitHub Actions зелёный.

---

## [ФАЗА 4] Observability & Testing Strategy

**Решение**: Prometheus + Grafana + Loki + Tempo + OpenTelemetry. k6 для нагрузки. Pact + proto-lint для контрактов.

**Артефакты**:
- `deploy/observability/otel-collector.yml` — OTLP receiver → batch → Tempo + Loki
- `deploy/observability/tempo.yml` — traces retention 24h, search enabled
- `deploy/observability/loki.yml` — logs retention 72h, structured metadata
- `deploy/observability/prometheus.yml` — scrape 7 service endpoints, 30d retention
- `deploy/observability/alerts.yml` — 7 Prometheus alert rules: HighErrorRate, HighLatency, ServiceDown, HighMemory, NATSLag, FailedHealthCheck, SAGACompensation, OutboxBacklog
- `deploy/observability/grafana-datasources.yml` — auto-provisioned Tempo + Loki + Prometheus
- `deploy/grafana/dashboards/raven-services.json` — 7-panel dashboard (health, RPS, latency, errors, memory, NATS lag, SAGA)
- `deploy/SLA.md` — SLO per service (p95 latency, error rate, throughput, availability)
- `scripts/telegram_alert_webhook.py` — AlertManager → Telegram webhook (Markdown)
- `tests/load/smoke.js` — k6 smoke: health + auth + monitors + RAG, 5 VUs, 30s
- `tests/load/endurance.js` — k6 endurance: 200 VUs, 9 min, multi-step flow
- `tests/load/healthcheck.js` — k6 healthcheck: 5 VUs, 30s, all 8 endpoints
- `tests/contract/test_pacts.py` — Pact tests: gateway ↔ auth, gateway ↔ agent

**Код/Конфиг**:
```bash
# Run load tests
k6 run tests/load/smoke.js --env BASE_URL=http://localhost:8000

# Run contract tests
pytest tests/contract/test_pacts.py -v

# Run alert webhook
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python scripts/telegram_alert_webhook.py
```

```yaml
# Alert rule example
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
  for: 2m
  labels:
    severity: critical
```

**Границы**: Alerts срабатывают при 5xx >1% за 5м. Auto-rollback при 5xx >5% (canary.yml). Метрики per-service, не агрегированные.

**Коммуникация**: OpenTelemetry spans → OTel Collector → Tempo. Logs → Loki. Metrics → Prometheus.

**Данные**: Retention: traces 24h, logs 72h, metrics 30d. All local (no SaaS).

**Оценка**: ~24 часа, риск Low. Точки отказа: AlertManager webhook timeout, Grafana provisioning race.

**Критерий приёмки**: `k6 run tests/load/smoke.js` — 0 failures, p95 <200ms. `pytest tests/contract/` — pact verification pass. Grafana `http://localhost:3000` показывает все 8 сервисов.

---

## [ФАЗА 5] Strangler Migration Plan

**Решение**: Feature flag per service + shadow traffic mode + promote/rollback скрипты. Пошаговое вырезание от channels до agent-core.

**Артефакты**:
- `raven/core/migration/flags.py` — FeatureFlag enum (14 флагов), FeatureFlagProvider (env FF_*)
- `raven/core/migration/proxy.py` — StranglerProxy: маршрутизация в monolith/ms, shadow сравнение
- `raven/core/migration/__init__.py` — публичный API модуля
- `scripts/migration/plan.py` — Интерактивный план миграции (7 шагов, dry-run режим)
- `scripts/migration/promote.py` — promote --shadow-only → enable shadow, promote → switch traffic
- `scripts/migration/rollback.py` — rollback --service / --all, <5 мин
- `scripts/migration/health-check.sh` — валидация: flags, health, NATS streams

**Код/Конфиг**:
```bash
# 1. Enable shadow mode for auth (dual-write, compare results)
python scripts/migration/promote.py --shadow-only --service auth

# 2. Monitor for drift (24h). Compare latency + error rate.
# 3. Switch traffic to microservice
python scripts/migration/promote.py --service auth

# 4. Rollback (if needed, <5 min)
python scripts/migration/rollback.py --service auth

# 5. Check health
bash scripts/migration/health-check.sh
```

```python
# StranglerProxy usage
proxy = StranglerProxy("auth", "http://auth:8001",
    FeatureFlag.USE_AUTH_SERVICE, FeatureFlag.SHADOW_AUTH)

# If FF disabled → monolith_fn. If shadow → both, compare. If enabled → microservice.
result = await proxy.proxy_or_call("POST", "/api/v1/auth/login",
    monolith_fn=lambda: login_monolith(body), body=body)
```

**Порядок выноса**:

| Шаг | Сервис | Риск | Стратегия |
|-----|--------|------|-----------|
| 1 | channels | Low | Event-driven adapters, stateless |
| 2 | monitor-engine | Low | Stateless workers, cron isolation |
| 3 | rag-service | Medium | Heavy deps isolation, vector DB |
| 4 | code-service | Medium | Sandbox execution isolation |
| 5 | task-engine | Medium | Tool policy boundary |
| 6 | auth | High | JWT/RBAC, session state, критический |
| 7 | agent-core | High | LLM routing, session state, последний |

**Границы**: Feature flags читаются из env (FF_*). Shadow mode не влияет на клиента — monolith response всегда возвращается.

**Коммуникация**: StranglerProxy → httpx → microservice (если флаг включён). В shadow mode: monolith + microservice параллельно.

**Данные**: Dual-write в shadow mode (оба сервиса пишут). Feature flag переключение — без потери данных.

**Наблюдаемость**: `health-check.sh` проверяет FF state + health endpoints + NATS. Warnings при расхождении monolith/ms в shadow mode.

**Оценка**: ~40 часов, риск High (auth, agent-core). Точки отказа: race condition при shadow switch, несовместимость данных при dual-write.

**Критерий приёмки**: `python scripts/migration/plan.py --dry-run` показывает все 7 шагов. `python scripts/migration/rollback.py --check` показывает `FF_* = false`. `python scripts/migration/promote.py --service auth` переключает `FF_use_auth_service=true`.

---

## Контрольные точки (STOP & VALIDATE)

| Проверка | Статус |
|----------|--------|
| 1. Нет cross-service DB queries | ✅ Database-per-service (SQLite embedded) |
| 2. Все write-эндпоинты имеют idempotency key | ✅ IdempotencyStore + middleware |
| 3. Каждый сервис имеет /health, /ready, /metrics | ✅ Вшито в каждый entrypoint |
| 4. Корреляция логов (X-Correlation-Id / trace_id) | ✅ JSON-логи + OpenTelemetry propagation |
| 5. Нет блокирующих синхронных вызовов >3 сервисов | ✅ NATS async-first, gRPC sync <500ms |
| 6. Откат возможен без потери данных | ✅ Feature flags + routing revert (<5 min) |
| 7. Тесты покрывают контракты | ✅ buf lint + proto contract + Pact |

## Итог

| Метрика | Значение |
|---------|----------|
| Фаз завершено | 5/5 |
| Новых файлов | ~120 |
| Строк кода | +6387 / -113 |
| Тестов | 875 passed, 6 skipped, 0 failed |
| ruff errors | 0 |
| Коммитов | 4 (f320b95 → 490bc02 → 6bfdb37 → HEAD) |
