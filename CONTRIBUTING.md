# Внесение вклада в Raven AI

_by [@ssrjkk](https://github.com/ssrjkk)_

Спасибо за интерес к Raven AI! Мы приветствуем вклад от всех желающих.

## Кодекс поведения

Участвуя в проекте, вы соглашаетесь поддерживать уважительную и инклюзивную атмосферу для всех участников.

## Как внести вклад

### 1. Сообщить об ошибке

- Проверьте существующие issues, чтобы избежать дубликатов
- Используйте шаблон баг-репорта
- Укажите: версию Python, ОС, шаги воспроизведения, ожидаемое и фактическое поведение
- Приложите логи и конфигурацию (без секретов)

### 2. Предложить идею

- Проверьте существующие issues и обсуждения
- Опишите проблему, а не только своё решение
- Объясните, как это помогает проекту

### 3. Pull Request

#### Настройка

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
```

#### Проверка перед коммитом

Единая точка входа — `scripts/check_all.py`: ruff, mypy, проверка импортов, CLI, тесты и фронтенд.

```bash
python scripts/check_all.py --quick               # линтер + типы + импорты + CLI, без тестов
python scripts/check_all.py                       # то же + все тесты
python scripts/check_all.py --cov                 # полный прогон с покрытием (как в CI на push)
python scripts/check_all.py --component core      # один компонент
```

Отдельные шаги, если нужен только один:

```bash
ruff check .
mypy raven/ aios/ ravencode/ plugins/ tests/ --ignore-missing-imports   # scripts/ исключён в pyproject
pytest tests/core/test_config.py -q --no-cov
cd web && npx tsc --noEmit && npm test -- --run
```

В `pyproject.toml` для pytest включены coverage-порог и allure, поэтому одиночный файл
тестов запускают с `--no-cov` — иначе отчёт о покрытии не сходится.

#### Правила

- **Стиль кода**: следуйте существующим паттернам; без лишних комментариев
- **Тесты**: добавляйте тесты на новый функционал; убедитесь, что все тесты проходят
- **Документация**: обновляйте docstring и соответствующие документы
- **Единственная ответственность**: один PR = одна фича или один баг-фикс
- **Сообщения коммитов**: краткие, описательные, в настоящем времени

#### Процесс PR

1. Сделайте форк репозитория
2. Создайте ветку для фичи (`git checkout -b feat/amazing-feature`)
3. Внесите изменения
4. Запустите линтер и тесты
5. Сделайте коммит с понятным сообщением
6. Запушьте в свой форк
7. Откройте Pull Request в ветку `main`
8. Ответьте на замечания в ревью

### 4. Структура проекта

```
raven/
├── raven/             # Основной Python-пакет (core, gateway, channels, tools, LLM, RAG, ...)
│   ├── channels/      # 15 каналов (Telegram, Discord, Slack, WhatsApp, ...)
│   ├── core/          # Движок: gateway, agents, security, task_engine, monitor, llm, rag
│   ├── cli/           # CLI (26 групп команд), tui
│   ├── tools/         # 66 инструментов ассистента
│   └── plugins/       # 10 встроенных плагинов
├── ravencode/         # Автономный coding-агент (runtime, agents, cli)
├── aios/              # Тонкий FastAPI bridge для AI-шлюза
├── web/               # React 19 + Vite + Tailwind дашборд
├── tests/             # Тесты (pytest)
├── docs/              # Документация MkDocs
├── deploy/            # Docker, systemd, observability
└── scripts/           # Скрипты установки и сборки
```

## Каналы разработки

- **stable**: Релизные версии из PyPI
- **dev**: Ветка `main` — может быть нестабильной

## Получить помощь

- Откройте [обсуждение](https://github.com/ssrjkk/raven/discussions)
- Напишите в Telegram: [@ssrjkk](https://t.me/ssrjkk)

## Лицензия

Внося вклад, вы соглашаетесь, что ваши изменения будут распространяться под лицензией MIT.
