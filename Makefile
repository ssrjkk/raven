.PHONY: lint lint-all test test-all test-quick test-integration test-coverage build build-web dev dev-web clean mypy allure install install-dev docker-up docker-down typecheck

# ── Installation ──────────────────────────────────────────────────────

install:
	pip install -e ".[dev]"
	pre-commit install

install-dev: install
	cd web && npm install
	cd desktop-tauri && npm install

# ── Python ────────────────────────────────────────────────────────────

lint:
	ruff check .

typecheck:
	mypy raven/ --strict --ignore-missing-imports || true

mypy:
	mypy raven/ --strict

lint-all: lint
	$(MAKE) go-lint
	$(MAKE) lint-web

test:
	pytest tests/ -v --cov=raven --cov-report=term --cov-report=xml

test-quick:
	pytest tests/ -m "not slow and not integration and not pact" -v

test-coverage:
	pytest tests/ -v --cov=raven --cov-report=html --cov-report=term

test-all: test
	$(MAKE) go-test
	$(MAKE) test-web-unit

test-integration:
	pytest tests/ -m "integration" -v --tb=long

allure:
	pytest tests/ -v --alluredir=allure-results
	allure generate allure-results -o allure-report --clean
	allure open allure-report

# ── Go ────────────────────────────────────────────────────────────────

go-lint:
	@for svc in gateway auth monitor-engine; do \
		echo "=== Linting services/$$svc ==="; \
		cd services/$$svc && go vet ./... && cd ../..; \
	done

go-test:
	@for svc in gateway auth monitor-engine; do \
		echo "=== Testing services/$$svc ==="; \
		cd services/$$svc && go test -v -race -count=1 ./... && cd ../..; \
	done

go-test-coverage:
	@for svc in gateway auth monitor-engine; do \
		echo "=== Coverage services/$$svc ==="; \
		cd services/$$svc && go test -v -race -coverprofile=coverage.out -covermode=atomic ./... && go tool cover -html=coverage.out -o coverage.html && cd ../..; \
	done

go-build:
	@for svc in gateway auth monitor-engine; do \
		echo "=== Building services/$$svc ==="; \
		cd services/$$svc && go build -o bin/ ./... && cd ../..; \
	done

# ── Web ───────────────────────────────────────────────────────────────

lint-web:
	cd web && npm run lint

test-web:
	cd web && npm run lint

test-web-unit:
	cd web && npx vitest run --reporter=verbose

test-web-e2e:
	cd web && npx playwright test

build-web:
	cd web && npm install && npm run build

dev-web:
	cd web && npm run dev

# ── Microservices ─────────────────────────────────────────────────────

docker-up:
	docker compose -f docker-compose.micro.yml up -d

docker-down:
	docker compose -f docker-compose.micro.yml down

docker-logs:
	docker compose -f docker-compose.micro.yml logs -f

docker-build:
	docker compose -f docker-compose.micro.yml build

# ── Docker (single container) ─────────────────────────────────────────

build:
	docker compose build

dev:
	raven start

# ── Cleanup ───────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf web/dist web/node_modules allure-results allure-report .benchmarks .mypy_cache .ruff_cache .pytest_cache
