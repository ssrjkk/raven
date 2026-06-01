# 📐 СТАНДАРТЫ МИКРОСЕРВИСНОЙ АРХИТЕКТУРЫ

## 1. Архитектурные границы и DDD
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 1.1 | Каждый микросервис соответствует одному Bounded Context по Evans DDD | Модуль в репозитории с изолированным go.mod/pyproject.toml; отсутствие shared-entity между модулями | `grep -r 'import.*services/' | grep -v proto` — ноль cross-imports между сервисами одного ранга | Неявные coupling между Bounded Context; orthogonal change приводит к каскадному редеплою | Mandatory | Evans, Domain-Driven Design (2003), гл. 4 |
| 1.2 | Aggregates — единственный способ модификации данных в границе | Repository pattern в каждом сервисе; прямой `INSERT`/`UPDATE` вне Repository запрещён | Code review: ни одного `db.Exec` вне `*Repository`-типа; статический анализ `grep -E '(Exec|Query).*INSERT|UPDATE'` без префикса `repo` | Нарушение инвариантов Aggregate; eventually-consistent данные без идемпотентности | Mandatory | Evans DDD, гл. 6; Vernon, Implementing DDD |
| 1.3 | Глубина графа вызовов не более 3 (service → service → service) | Все cross-service вызовы через gateway (1 hop); chain из 4+ сервисов запрещён | `tracing: span_graph_depth <= 3` в 95% трассировок по Jaeger/Grafana Tempo | Каскадные таймауты; P50 latency растёт экспоненциально с глубиной | Mandatory | Google SRE Book, ch. 6; Netflix Tech Blog |
| 1.4 | Database-per-service — физическая изоляция, не только логическая | Разные SQLite-файлы или отдельные схемы БД; `CROSS_DB_JOIN` запрещён | `grep -r 'ATTACH DATABASE\|CROSS JOIN'` — 0 результатов | O(n) сложность миграций; единая точка отказа БД | Mandatory | Twelve-Factor App — Backing Services; Sam Newman, Building Microservices |

## 2. Контракты API и версионирование
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 2.1 | Proto-файлы — source of truth для всех gRPC API; кодогенерация обязательна | `buf generate` из `services/proto/` → `services/proto/go/` и Python stubs; рукописные DTO для API запрещены | CI: `buf breaking --against .git` — проход; `grep -r 'type.*struct' services/proto/` — 0 (все типы в .proto) | Breaking-изменения без детекта в рантайме; клиенты падают с `Unimplemented` | Mandatory | buf.build/docs; gRPC Best Practices |
| 2.2 | Версионирование через package в proto: `v1/`, `v2/` | `package auth.v1;` в proto; HTTP-роутинг: `/api/v1/auth/` | Code review: `grep 'package.*v1'` существует; отсутствует `package auth` без версии | Невозможность параллельного существования версий; вынужденный big-bang deploy | Mandatory | Google API Design Guide |
| 2.3 | Backward-compatible изменения: добавление полей, новых RPC — допустимо. Breaking: удаление/переименование поля/метода — запрещено без мажорной версии | Proto поле `reserved 2, 4 to 8;` для удалённых; `buf breaking` в CI | CI: `buf breaking --against origin/main` — exit 0 | Клиенты десериализуют мусор; silent data corruption | Mandatory | buf breaking change rules; protobuf spec |
| 2.4 | Все HTTP API — RESTful: ресурсные пути, правильные HTTP методы | `GET /api/v1/monitors`, `POST /api/v1/monitors`, `DELETE /api/v1/monitors/{id}` | `grep -E 'HandleFunc\("(GET\|POST\|PUT\|DELETE)'` — соответствует REST; `HandleFunc\(".*POST.*GET'` — 0 | Неинтуитивные API; клиентский код с хардкодом путей | Recommended | REST Dissertation (Fielding); Microsoft REST Guidelines |

## 3. Коммуникация (синхронная/асинхронная) и отказоустойчивость
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 3.1 | Все синхронные вызовы имеют таймаут: P99 × 3, но не более 30s | `grpc.WithTimeout(5s)`; HTTP client `Timeout: 30 * time.Second` | Code review: `grep -E 'http\.Client\|grpc\.Dial'` — обязателен параметр `Timeout` | Cascading failure: зависший downstream блокирует все горутины/threads | Mandatory | Google SRE Book, ch. 22 (Tailing Timeouts); Netflix Hystrix |
| 3.2 | Circuit Breaker на каждый downstream | В gateway: middleware с `half-open` (3 успешных → закрыт, 5 ошибок → открыт на 30s) | Unit test: последовательность `allow→allow→fail×5→deny→wait 30s→allow→allow×3→allow` | Каскадный отказ при недоступности downstream; latency spike до таймаута | Mandatory | Netflix Hystrix Wiki; Istio DestinationRule (outlierDetection) |
| 3.3 | Асинхронная коммуникация — только через NATS JetStream с at-least-once | `nc.Publish` + `js.Publish` (persisted) для событий; без fire-and-forget каналов | `grep -r 'nats\.Conn\|jetstream\.JetStream'` — каждый publish использует `js.Publish` или `nc.Publish` | Потеря событий при краше publisher; невозможность exactly-once без идемпотентности | Mandatory | NATS JetStream docs; CNCF CloudEvents |
| 3.4 | Idempotency key на мутирующие POST запросы | Header `X-Idempotency-Key` → `IdempotencyStore.get/set` с TTL 24h | Integration test: повтор POST с тем же ключом → HTTP 200 (не 201) и тот же response body | Дублирование операций: повторный платёж, создание дубликата задачи | Mandatory | Stripe API docs; Google Cloud Tasks |
| 3.5 | Outbox pattern для событий, которые должны быть доставлены атомарно с БД-транзакцией | `OutboxStore.enqueue()` внутри той же транзакции (SQLite); background worker флашит в NATS | `grep -r 'enqueue\|publish'` — сопоставить с `BeginTx/Commit`; проверить отсутствие publish до commit | Отправка события при откате транзакции; потеря события при успешном commit | Contextual | Microsoft eShopOnContainers; Debezium Outbox |

## 4. Управление данными и консистентность
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 4.1 | Все БД — WAL mode, устойчивы к крашу процесса | `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` при инициализации SQLite | `grep -r 'PRAGMA' | grep -E 'WAL\|journal_mode'` — каждый сервис с БД имеет WAL | Потеря данных при `SIGKILL`; блокировка базы при конкурентных запросах | Mandatory | SQLite WAL docs; Twelve-Factor App — Disposability |
| 4.2 | Нет cross-service транзакций — Saga pattern с компенсацией | Каждая мутация генерирует событие; компенсирующее действие подписывается на `*.failed` или `*.compensate` | Code review: `grep -r 'BeginTx\|ROLLBACK'` в gateway — 0 (нет distributed tx) | Жёсткая связанность; блокировки на уровне БД; P99 латентность > 1s | Mandatory | Sam Newman, Building Microservices ch. 8; AWS Saga |
| 4.3 | Индексы на всех полях, используемых в WHERE/ORDER BY | `CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)`; анализ EXPLAIN QUERY PLAN | EXPLAIN QUERY PLAN для каждого CRUD запроса — нет full table scan; `grep -r 'ORDER BY\|WHERE' .sql` — есть `CREATE INDEX` для каждого | Деградация производительности при росте данных; full table scans на таблицах >10k строк | Mandatory | SQLite Query Planning; PostgreSQL Indexing |
| 4.4 | TTL и cleanup старых записей: не более 30 дней в operational БД | Периодическая горутина/task: `DELETE FROM tasks WHERE created_at < ? AND status IN ('completed','failed')` | `grep -r 'DELETE.*WHERE.*created_at\|TTL\|cleanup\|retention'` — реализация в каждом сервисе с БД | База растёт бесконтрольно; backup окно > RTO; стоимость хранения > бюджета | Mandatory | AWS Well-Architected — Data Lifecycle; ISO/IEC 25010 |

## 5. Наблюдаемость (Observability)
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 5.1 | Каждый сервис экспортирует метрики на `/metrics` в формате Prometheus | `promhttp.Handler()`; метрики: requests_total, duration_seconds, errors_total, in_flight | CI: curl `localhost:$PORT/metrics` → `HTTP 200` + `Content-Type: text/plain.*0.0.4` | Невозможность алертинга; слепое развёртывание без SLO | Mandatory | OpenMetrics / Prometheus Exposition Format; Google SRE Book ch. 6 |
| 5.2 | Distributed tracing через OpenTelemetry: каждый inbound/outbound запрос | OTel SDK + `otelhttp.NewHandler()`; propagation через `TraceContext` + `Baggage` headers | Jaeger/Tempo: 100% трассировок имеют `trace_id` и `span_id`; `0 spans with missing parent` | Невозможность диагностировать latency в графе сервисов | Mandatory | OpenTelemetry Specification; W3C TraceContext |
| 5.3 | Структурированное логирование JSON; никаких `fmt.Println`/`print` | `slog.NewJSONHandler(os.Stdout)` или `loguru` с сериализацией в JSON; поля: level, time, msg, service, trace_id | `grep -r 'fmt\.Print\|print('` — 0; каждый логгер — JSON-формат | Невозможность парсинга логов в ELK/Loki; потеря полей при агрегации | Mandatory | Twelve-Factor App — Logs; Google SRE ch. 5 |
| 5.4 | Health check endpoints: `/health` (liveness) и `/ready` (readiness) | `/health` — всегда 200, `/ready` — проверяет зависимости (БД, NATS) и выдаёт 503 если не готов | CI: `curl localhost/health` → 200, `curl localhost/ready` → 503 (без БД) или 200 (с БД) | K8s убивает живой pod; трафик направляется на неготовый pod | Mandatory | K8s Pod Lifecycle; Google SRE Best Practices |
| 5.5 | SLO мониторинг: latency P99 < 500ms, availability > 99.9% | Prometheus recording rules: `latency_bucket{le="0.5"}` / `latency_count`; алерт если burn rate > 2 за 1h | Grafana dashboard: SLO compliance last 30d; отсутствие violation window > 1h | Нарушение SLA без детекта; субъективные оценки вместо метрик | Mandatory | Google SRE Book ch. 4-5; Service Level Indicators |

## 6. Безопасность и Zero-Trust
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 6.1 | Все межсервисное взаимодействие — mTLS (gRPC) или JWT (HTTP/gRPC) | `credentials.NewTLS()`; каждый запрос через gateway содержит `Authorization: Bearer <jwt>` в заголовке | `grep -r 'WithTransportCredentials\|Authorization'` — нет вызовов без auth; `insecure.NewCredentials()` — только на dev | Перехват токена в plaintext; replay-атака; несанкционированный доступ к внутренним API | Mandatory | OWASP ASVS V2 (Authentication); SPIFFE/SPIRE |
| 6.2 | JWT signing: минимум RS256/ES256, HMAC запрещён для inter-service | `jwt.SigningMethodRS256{}` или `ES256`; `SigningMethodHS256` только для client-facing gateway | `grep -r 'SigningMethodHS'` — нет; `grep -r 'SigningMethodRSA\|SigningMethodECDSA'` — есть | Компрометация shared secret → подделка любого токена | Mandatory | JWT Best Practices (RFC 8725); OWASP JWT Cheatsheet |
| 6.3 | Secrets — не в репозитории, всегда через Secret Manager | K8s Secret + `secretKeyRef`; env: `JWT_SECRET` из Vault/AWS Secrets Manager/K8s Secret | `grep -r 'JWT_SECRET\|DB_PASSWORD\|API_KEY' *.go *.py | grep -v 'os.Getenv\|secretKeyRef\|valueFrom'` — 0 | Креды в git → compromise всей production среды | Mandatory | OWASP ASVS V8 (Data Protection); GitOps Manifesto |
| 6.4 | Rate limiting per-IP и per-user: аутентифицированные — 1000 req/min, неаутентифицированные — 100 req/min | Token bucket middleware; ключ: `remote_addr` для анонимных, `user:<id>` для аутентифицированных | Load test: 200 req/min с одного IP → HTTP 429 после 100-й (без токена) | DoS с одного IP кладёт весь gateway; бесплатный вызов дорогих upstream | Mandatory | OWASP ASVS V1 Architecture; Cloudflare Rate Limiting |
| 6.5 | Никакой service-to-service без авторизации: каждое действие проверяет permission | `CheckPermission(role, permission)` gRPC call на auth; policy в коде `if role != "admin" { deny }` | Code review: каждая мутирующая ручка вызывает `CheckPermission` или содержит `if role == "admin"` | Privilege escalation: user создаёт/удаляет ресурсы других пользователей | Mandatory | OWASP ASVS V3 (Access Control); Google Zanzibar |

## 7. CI/CD, упаковка и развёртывание
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 7.1 | Каждый сервис — отдельный Docker image; один Dockerfile на сервис | `services/*/Dockerfile` → `docker build -t raven/$service .`; мульти-сервисные образы запрещены | `Get-ChildItem Dockerfile -Recurse` — один Dockerfile на сервис; `grep -r 'FROM.*base'` — нет shared image | Невозможность независимого деплоя; каскадные изменения при обновлении base image | Mandatory | Docker Best Practices; Twelve-Factor App — Build/Release/Run |
| 7.2 | Go сборка: `CGO_ENABLED=0`, scratch/alpine base, strip debug symbols | `CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app .` | Docker image: `docker scout` — 0 critical/high CVEs; image size < 50MB для Go сервиса | Образ > 200MB; уязвимости libc; медленный pull на ноду | Mandatory | Docker official guidelines; Go build security |
| 7.3 | CI pipeline: lint → unit tests → build → container scan → integration → deploy | GitHub Actions: jobs `lint → go-build/test-monolith → docker-build (trivy scan) → nats-smoke/k6-smoke` | Pipeline status: green на main; `docker-build` включает `trivy scan --severity CRITICAL,HIGH` | Уязвимости попадают в production; сломанные тесты деплоятся | Mandatory | GitOps Manifesto (Weaveworks); OWASP Top 10 CI/CD |
| 7.4 | Zero-downtime deploy: rolling update с minReadySeconds + readiness probe | K8s `strategy.type: RollingUpdate`, `maxSurge: 1`, `maxUnavailable: 0`; `readinessProbe.periodSeconds: 10` | Load test во время deploy: 0 errors, P99 не превышает baseline +20% | Прерывание запросов при деплое; 502 ошибки | Mandatory | K8s Deployment docs; Google SRE ch. 15 |
| 7.5 | Container image tag = git commit SHA; latest tag — secondary | `docker tag $sha && docker tag $sha latest`; версионирование через `$IMAGE_TAG: ${{ github.sha }}` | `git log --oneline` ↔ docker image tags: каждый commit → уникальный tag | Невозможность rollback; "что сейчас в production?" — неизвестно | Mandatory | GitOps Manifesto; Docker tag best practices |

## 8. Эксплуатация, SRE и SLO
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 8.1 | SLO: availability >= 99.9% за 30d rolling window | `sli_availability = requests_total / (requests_total + errors_total)`; алерт если < 99.9% за любой 1h | Grafana: `availability_30d` ≥ 0.999; PagerDuty алерт при нарушении burn rate | SLA клиентов нарушены; репутационные потери | Mandatory | Google SRE Book ch. 4 |
| 8.2 | Error budget: оставшийся бюджет на деплой = 100% - current_error_rate × window; depoy запрещён при исчерпании | CI job: `curl prometheus/api/v1/query?query=error_budget_remaining`; если < 20% → блокировка merge | `error_budget_remaining{service="gateway"} < 0.2` в Prometheus → merge заблокирован в GitHub | Деплой в нестабильную систему усугубляет outage | Contextual | Google SRE Book ch. 5; Error Budget Policy |
| 8.3 | Каждый сервис имеет runbook: алерт → диагноз → действие → ETA | Файл `deploy/standards/runbooks/<service>.md` с шаблоном: symptom, check, resolve, escalate | `Test-Path deploy/standards/runbooks/*.md` — каждый сервис имеет runbook | Инцидент длится часы вместо минут; escalation в неправильную команду | Mandatory | Google SRE Book ch. 15; PagerDuty Runbook |
| 8.4 | Graceful shutdown: SIGTERM → drain connections → close dependencies → exit | `signal.Notify(quit, syscall.SIGTERM, SIGINT)`; shutdown order: gRPC GracefulStop → HTTP Shutdown → DB.Close | Load test: `kill -TERM $PID` во время запроса → 0 dropped запросов (HTTP 200) | Pod убит K8s → клиенты получают 502/GOAWAY | Mandatory | K8s Pod Termination; AWS Well-Architected |

## 9. Организационные и процессные стандарты
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 9.1 | Каждый сервис обслуживается одной командой (2-pizza team: 6-12 чел.) | `CODEOWNERS` — один owner team на сервис; `service/auth/CODEOWNERS → @team-auth` | `git shortlog -sne -- services/auth/` — ≤ 12 contributors/квартал | Bus factor = 1; принятие решений без контекста | Recommended | Conway's Law; Amazon 2-pizza team |
| 9.2 | RFC процесс для архитектурных решений: PR с markdown RFC, review минимум 3 senior инженеров | `docs/rfcs/<number>-<title>.md`; обязательные секции: Problem, Solution, Alternatives, Risks | Data: количество RFC с ≥ 3 approvals / общее количество RFC ≥ 0.8 | Субъективные решения без анализа альтернатив; технический долг | Contextual | AWS Architect Framework; C4 model |
| 9.3 | On-call ротация: primary+secondary, 8h смены, escalation path до архитектора | PagerDuty/AlertManager schedule: 1w primary, 1w secondary; escalation — дежурный SRE | MTTA < 15min, MTTR < 1h для P1; подтверждение алерта < 5min | Инцидент без ответственного; выгорание команды | Mandatory | Google SRE Book ch. 11; PagerDuty Best Practices |

## 10. Документация и артефакты
| # | Правило | Реализация | Валидация | Последствие нарушения | Уровень | Источник |
|---|---------|------------|-----------|------------------------|---------|----------|
| 10.1 | Каждый сервис имеет README.md с: purpose, API reference, runbook ссылка, local dev | `services/*/README.md` с обязательными секциями: What, API, Run, Test, Dependencies | `Test-Path services/*/README.md` — каждый сервис; секции >= 3 | Онбординг новой команды: недели вместо часов | Mandatory | Spotify Backstage docs; CNCF project standards |
| 10.2 | OpenAPI/gRPC proto как единственный источник документации API | `buf generate` + `protoc-gen-openapi`; рукописная API документация запрещена | CI: `buf generate` — чистый выход; отсутствие .md файлов с рукописными описаниями API | Документация расходится с кодом; breaking change не замечен | Mandatory | Buf Schema Registry; OpenAPI 3.0 |
| 10.3 | Changelog: запись каждого breaking change с миграционным планом | `CHANGELOG.md` или GitHub Release Notes с секциями Breaking, Features, Fixes | `git log --oneline v1.0.0..HEAD | grep -i breaking\|migration` — changelog entry для каждого | Клиенты не знают о breaking change; production инциденты при upgrade | Mandatory | Keep a Changelog (Vandevorst); SemVer spec |

## 11. Запрещённые антипаттерны
| # | Антипаттерн | Почему ломает | Как детектить в CI/CD | Severity |
|---|------------|---------------|----------------------|----------|
| 11.1 | **Shared Database**: несколько сервисов читают/пишут в одну БД | Нарушение Bounded Context; одна миграция блокирует все сервисы; impossible to scale | `grep -r 'ATTACH DATABASE\|CREATE TABLE.*IF NOT EXISTS'` в gateway — 0; сервисы подключаются к разным .db файлам | Critical |
| 11.2 | **Sync Chain**: A → B → C → D синхронно | P99 latency = sum(timeout всех каскадов); каскадный отказ при падении D | `tracing: span_graph_depth > 3` в Jaeger: trigger failed CI stage | Critical |
| 11.3 | **Fire-and-Forget**: publish события без подтверждения | Потеря события при краше; отсутствие гарантий доставки | `grep -r '\(Publish\|publish\)' | grep -v 'JetStream\|js\.Publish\|nc\.Publish'` — нет raw NATS publish | Critical |
| 11.4 | **Hand-written DTO**: struct/class дублирует proto-тип вручную | Diff между proto и кодом; баги десериализации | `grep -r 'type.*struct' $(grep -l 'proto\|protobuf')` — если struct не `.pb.go`, rejected | High |
| 11.5 | **No timeouts**: http.Client без Timeout, gRPC без WithTimeout | Горутина/thread навсегда; утечка памяти; зависший сервис | `grep -r 'http\.Client{}\|http\.Client{}' | grep -v 'Timeout'` — 0; `grpc.WithTimeout` обязателен | Critical |
| 11.6 | **LLM/ML в critical path синхронного API**: LLM вызов внутри HTTP handler с таймаутом < 30s | P95 latency > 10s; отказ LLM → отказ всего API; cost explosion | Code review: `grep -r 'openai\|llm\|model\.generate\|anthropic'` внутри `func.*Handler\|func.*handler` — reject | Critical |
| 11.7 | **Config в runtime без перезагрузки**: env vars читаются один раз при старте и не обновляются | Требуется рестарт для смены log level/rate limit; увеличение MTTR | `grep -r 'os\.Getenv\|os\.LookupEnv'` — читают только в main/init; reload механизм (SIGHUP/signal) для изменяемых параметров | High |

## 12. Уровни соответствия (Mandatory / Recommended / Contextual)

| Уровень | Правило | Исключение | Частота аудита |
|---------|---------|-----------|----------------|
| **Mandatory** | Нарушение приводит к inability to meet SLO/SLA, security breach, или data loss | Только с Exception Approval от Architecture Review Board | Каждый PR |
| **Recommended** | Best practice — соблюдение желательно, deviation допустим с документированным обоснованием | Tech Lead ревью и комментарий в PR | Каждый квартал |
| **Contextual** | Applicable при определённых условиях (напр. — only for event-driven, only for enterprise >100 endpoints) | Выбор инструмента/подхода зависит от контекста; обязателен Architecture Decision Record | Каждый ADR |

## ✅ АВТОМАТИЗИРОВАННЫЙ ЧЕК-ЛИСТ ВХОДА В PRODUCTION
- [ ] **1.1** Ни одного cross-import между сервисами одного ранга (кроме proto)
- [ ] **1.3** Глубина графа трассировки ≤ 3 (95% трассировок)
- [ ] **2.1** `buf breaking --against origin/main` — exit 0
- [ ] **2.3** Нет удалённых полей без `reserved`
- [ ] **3.1** Каждый HTTP/gRPC вызов имеет Timeout (≤30s)
- [ ] **3.2** Circuit Breaker реализован для каждого downstream
- [ ] **3.4** Все мутирующие POST запросы принимают `X-Idempotency-Key`
- [ ] **4.1** Все SQLite БД в WAL mode
- [ ] **4.3** EXPLAIN QUERY PLAN — 0 full table scans
- [ ] **5.1** `/metrics` endpoint отдаёт Prometheus format
- [ ] **5.2** OpenTelemetry propagation через TraceContext
- [ ] **5.3** Структурированное логирование JSON (нет `print`)
- [ ] **5.4** `/health` и `/ready` endpoints с корректным поведением
- [ ] **6.1** Все межсервисные вызовы авторизованы (JWT или mTLS)
- [ ] **6.4** Rate limiter активен (200 req/min burst=20 для анонимных)
- [ ] **7.1** Один Dockerfile на сервис, CGO_ENABLED=0
- [ ] **7.4** RollingUpdate: maxSurge=1, maxUnavailable=0
- [ ] **8.1** SLO availability ≥ 99.9% за 30d
- [ ] **8.4** Graceful shutdown: SIGTERM → drain → exit (0 dropped запросов)
- [ ] **11.1** Нет shared database (каждый сервис — свой .db)
- [ ] **11.2** Нет sync chain длиннее 3 сервисов

## 🔗 ВЕРИФИЦИРУЕМЫЕ ИСТОЧНИКИ
- [Domain-Driven Design (Eric Evans, 2003)](https://www.domainlanguage.com/ddd/)
- [Building Microservices (Sam Newman, 2nd ed.)](https://samnewman.io/books/building-microservices-2nd/)
- [Google SRE Book](https://sre.google/sre-book/table-of-contents/)
- [Google SRE Workbook](https://sre.google/workbook/table-of-contents/)
- [Twelve-Factor App](https://12factor.net/)
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)
- [OWASP ASVS (Application Security Verification Standard)](https://owasp.org/www-project-application-security-verification-standard/)
- [CNCF CloudEvents](https://cloudevents.io/)
- [GitOps Manifesto (Weaveworks)](https://www.weave.works/technologies/gitops/)
- [Protobuf Style Guide](https://protobuf.dev/programming-guides/style/)
- [Buf Breaking Change Rules](https://buf.build/docs/breaking/rules)
- [Kubernetes Production Best Practices](https://learnk8s.io/production-best-practices)
- [NATS JetStream Documentation](https://docs.nats.io/nats-concepts/jetstream)
- [Docker Official Images Guidelines](https://docs.docker.com/develop/develop-images/guidelines/)
- [JWT Best Current Practices (RFC 8725)](https://www.rfc-editor.org/rfc/rfc8725)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [ISO/IEC 25010:2023 Systems and software Quality Requirements](https://www.iso.org/standard/78176.html)
