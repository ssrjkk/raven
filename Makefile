.PHONY: lint test test-web build build-web dev dev-web clean mypy allure

# Python
lint:
	ruff check .
	mypy raven/ --strict --ignore-missing-imports || true

mypy:
	mypy raven/ --strict

test:
	pytest tests/ -v --cov=raven --cov-report=term --cov-report=xml

test-quick:
	pytest tests/ -m "not slow and not integration and not pact" -v

test-coverage:
	pytest tests/ -v --cov=raven --cov-report=html --cov-report=term

allure:
	pytest tests/ -v --alluredir=allure-results
	allure generate allure-results -o allure-report --clean
	allure open allure-report

# Go
go-lint:
	@for svc in gateway auth monitor-engine; do \
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

# Web
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

# Docker
build:
	docker compose build

dev:
	raven start

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf web/dist web/node_modules allure-results allure-report
