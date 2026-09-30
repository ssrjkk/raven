<div align="center">

# Raven

**от [@ssrjkk](https://github.com/ssrjkk)**

Самостоятельно размещаемый AI-ассистент: 15 мессенджеров, автономный coding-агент и веб-дашборд
в одном Python-процессе.

[English](README.md) • **Русский**

[![CI](https://img.shields.io/github/actions/workflow/status/ssrjkk/raven/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ssrjkk/raven/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

## Что это

Две программы с общим ядром:

- **RavenCode** — coding-агент: читает репозиторий, правит файлы, запускает тесты, коммитит.
  Контекст обогащается через серверы языков (pyright, tsserver, gopls, rust-analyzer),
  сессии чекпоинтя́тся и откатываются, есть режимы plan/safe/fast.
- **RavenFlow** — workflow-демон: соединяет агента с мессенджерами, маршрутизирует сообщения
  между агентами, стримит ответы по WebSocket, выполняет рутины по расписанию и мониторы.

Под ними — общий шлюз: 15 каналов связи, планировщик задач, RAG-память (эмбеддинги + BM25,
всё локально), голосовой ввод/вывод и веб-дашборд на React с редактором Monaco.

## Требования

- Python 3.11+ и хотя бы один API-ключ LLM — или локальный Ollama/vLLM
- Node.js 22+ только если пересобираете веб-дашборд из исходников
- Docker опционален — вся система работает одним процессом

## Быстрый старт

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven
pip install -e .

cp .env.example .env        # впишите хотя бы один API-ключ LLM
raven onboard               # интерактивный мастер настройки
raven start                 # шлюз + веб-интерфейс на http://localhost:18888
```

Три точки входа:

| Команда | Что запускает |
|---|---|
| `raven start` | Шлюз: каналы, веб-дашборд на порту 18888 |
| `ravencode tui` | Coding-агент в терминале |
| `ravenflow` | Workflow-демон на порту 18789 |

Или через Docker:

```bash
docker compose up -d
```

## Умеет

**Общается** — Telegram (инлайн-кнопки, голосовые), Discord, Slack, WhatsApp, Matrix, Teams,
Signal, IRC, LINE, Feishu, Google Chat, GitHub, GitLab, почта и встроенный веб-чат.
Личные сообщения закрываются кодом сопряжения (pairing), поведение в группах настраивается
на каждый канал.

**Пишет код** — агент читает проект, подтягивает определения через LSP, правит файлы,
прогоняет тесты, делает коммиты. Каждая сессия чекпоинтится, `undo_changes` откатывает
изменения. Режим plan показывает, что он собирается сделать, не записывая ничего.

**Помнит** — память разговора плюс база знаний по документам: чанкинг PDF/текста/кода,
эмбеддинги (OpenAI или локальные) и BM25-поиск. Всё хранится локально.

**Работает по расписанию** — рутины (утренние сводки, проверка почты) и мониторы, которые
следят за URL, ценой, RSS-лентой, файлом или процессом и шлют алерт, когда условие сработало.

**Переключает модели** — десять провайдеров (OpenAI, Anthropic, OpenRouter, Ollama, vLLM,
Azure, Groq, Bedrock, Vertex AI, Copilot) за одним роутером: circuit breaker и бэкофф при
рейт-лимитах. Если модель начала сбоить, диалог подхватывает следующая.

**Остаётся безопасным** — JWT с ролями, политика allow/deny по каждому инструменту, пять
sandbox-профилей для исполнения кода, изоляция workspace с защитой от symlink-побега,
SSRF-проверка каждого исходящего запроса, шифрование секретов (Fernet), журнал аудита.
Подробно — в [docs/security/overview.md](docs/security/overview.md).

## Шпаргалка по CLI

```bash
raven start / stop / status    # управление шлюзом
raven doctor                   # диагностика
raven tui                      # терминальная панель
raven agent --message "..."    # разовый вопрос
raven code start --goal "..." --project ./my-project
raven code review <file>       # AI-ревью файла
raven task run "<цель>"        # многошаговая задача
raven monitor add ...          # следить за URL / ценой / лентой / файлом / процессом
raven routine add ...          # рутина по расписанию
raven security audit --deep    # аудит окружения, сети, зависимостей
raven db backup                # бэкап базы
raven models list              # настроенные LLM-провайдеры
```

Полный справочник — в самом CLI: `raven --help`, по группам — `<команда> --help`.

## Настройка

Всё конфигурируется переменными окружения (`.env` ищется в директории проекта,
`~/.raven/.env` и корне установки). Главное:

```bash
# LLM — хотя бы один провайдер
OPENAI_API_KEY=sk-...
# или локальный сервер:
OLLAMA_BASE_URL=http://localhost:11434

DEFAULT_MODEL=openrouter/openai/gpt-4o

# Веб-интерфейс
WEB_PORT=18888
WEB_SECRET_KEY=<openssl rand -hex 32>

# Предохранители
TOOLS_PROFILE=messaging    # messaging | minimal | full — какие инструменты включены
EXEC_SECURITY=deny         # deny | ask | full — политика шелл-команд
DM_POLICY=pairing          # pairing | closed | open
SANDBOX_MODE=non-main      # main | non-main | all | none

# PostgreSQL вместо SQLite (опционально)
DATABASE_URL=postgresql://user:pass@localhost:5432/raven
```

Полный список с описаниями — в [.env.example](.env.example).

## Архитектура

```
Каналы (15)                   Telegram │ Discord │ Slack │ … │ Веб-чат
                                  │
Шлюз (FastAPI)                auth → rate limit → circuit breaker → маршрутизация агентов
                                  │
        ┌─────────────────┬──────┴────────┬──────────────────┐
  RavenCode агент    Планировщик     Рутины и мониторы    RAG-память
        │                 │               │                  │
  Реестр инструментов (66) — файлы, bash, git, веб, БД, canvas, cron
        │
  SQLite / PostgreSQL          LLM-роутер → Ollama, OpenRouter, OpenAI, Anthropic, …
```

Один процесс обслуживает всё. Рядом можно поднять PostgreSQL, NATS или стек
Prometheus/Grafana — см. [docker-compose.postgres.yml](docker-compose.postgres.yml)
и [docker-compose.monitoring.yml](docker-compose.monitoring.yml).

## Структура проекта

```
raven/        шлюз: каналы, CLI, безопасность, задачи, мониторы, RAG, рутины
ravencode/    coding-агент: ReAct-цикл, LSP, сессии, 66 инструментов
aios/         FastAPI-мост для веб-IDE
web/          дашборд на React 19 + Vite (SPA)
extension/    браузерное расширение (MV3) + расширение VS Code
docs/         документация разработчика (архитектура, безопасность, каналы)
tests/        pytest-набор (unit, integration, e2e)
```

## Разработка

```bash
pip install -e ".[dev]"
cd web && npm install && cd ..

python scripts/check_all.py          # ruff + mypy + импорты + все тесты
python scripts/check_all.py --quick  # только линт + типы + импорты
```

CI гоняет тот же набор на каждый push: Linux (Python 3.11 и 3.12), Windows, сборка фронтенда,
интеграция с Postgres, E2E, проверка зависимостей, поиск секретов, CodeQL и сборка Docker-образа
с проверкой импортов внутри него.

## Развёртывание

```bash
# Docker
docker compose up -d

# systemd
sudo cp deploy/raven.service /etc/systemd/system/
sudo systemctl enable --now raven

# macOS
cp deploy/com.raven.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.raven.plist
```

## Если что-то не работает

```bash
raven doctor          # проверяет конфиг, БД, провайдеров, каналы
tail -f data/raven.log
```

- **Порт 18888 занят** — задайте `WEB_PORT=18889` в `.env`.
- **Ошибки LLM** — `raven models list` покажет, что настроено; проверьте ключи и квоты.
- **База данных** — проверьте `DATABASE_URL`; контейнер PostgreSQL: `docker compose -f docker-compose.postgres.yml up -d`.

## Документация

- [Архитектура](docs/concepts/architecture.md)
- [English version](README.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [License](LICENSE)

## Контакты

- **GitHub:** https://github.com/ssrjkk/raven
- **Issues:** https://github.com/ssrjkk/raven/issues

## Лицензия

MIT — см. [LICENSE](LICENSE).
